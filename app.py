import pymysql
pymysql.install_as_MySQLdb()

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, date
import os
from decimal import Decimal
import json
from config import Config
from sqlalchemy import Numeric
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps


app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

# Database Configuration
app.config.from_object(Config)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'finance-tracker-secret-key-2024'

# Initialize SQLAlchemy
db = SQLAlchemy(app)


# ─────────────────────────── Models ───────────────────────────

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transactions = db.relationship('Transaction', backref='user', lazy=True, cascade='all, delete-orphan')
    budgets = db.relationship('Budget', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(10), nullable=False)   # 'income' or 'expense'
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'amount': float(self.amount),
            'category': self.category,
            'description': self.description,
            'date': self.date.isoformat(),
            'created_at': self.created_at.isoformat()
        }


class Category(db.Model):
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    type = db.Column(db.String(10), nullable=False)   # 'income' or 'expense'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type
        }


class Budget(db.Model):
    __tablename__ = 'budgets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'amount': float(self.amount),
            'month': self.month,
            'year': self.year
        }


# ─────────────────────────── Helpers ───────────────────────────

def login_required(f):
    """Redirect to login page if the user is not authenticated."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def api_login_required(f):
    """Return 401 JSON if the user is not authenticated (for API routes)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function


# ─────────────────────────── DB Init ───────────────────────────

from sqlalchemy import inspect, text

_tables_initialized = False

@app.before_request
def create_tables():
    global _tables_initialized
    if _tables_initialized:
        return
    _tables_initialized = True

    inspector = inspect(db.engine)

    # Create any completely missing tables
    db.create_all()

    # ── Migration: add user_id to transactions if it doesn't exist yet ──
    if inspector.has_table('transactions'):
        existing_cols = [c['name'] for c in inspector.get_columns('transactions')]
        if 'user_id' not in existing_cols:
            with db.engine.connect() as conn:
                # Add nullable first, then we'll handle orphan rows
                conn.execute(text(
                    "ALTER TABLE transactions ADD COLUMN user_id INT NULL"
                ))
                conn.commit()

    # ── Migration: add user_id to budgets if it doesn't exist yet ──
    if inspector.has_table('budgets'):
        existing_cols = [c['name'] for c in inspector.get_columns('budgets')]
        if 'user_id' not in existing_cols:
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE budgets ADD COLUMN user_id INT NULL"
                ))
                conn.commit()

    # ── Seed default categories (shared/global) ──
    if Category.query.count() == 0:
        default_categories = [
            Category(name='Salary', type='income'),
            Category(name='Freelance', type='income'),
            Category(name='Investment', type='income'),
            Category(name='Gift', type='income'),
            Category(name='Other Income', type='income'),
            Category(name='Food', type='expense'),
            Category(name='Transportation', type='expense'),
            Category(name='Entertainment', type='expense'),
            Category(name='Bills', type='expense'),
            Category(name='Shopping', type='expense'),
            Category(name='Healthcare', type='expense'),
            Category(name='Other Expense', type='expense'),
        ]
        for category in default_categories:
            db.session.add(category)
        db.session.commit()


# ─────────────────────────── Auth Routes ───────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validation
        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('register.html')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('register.html')

        # Check if email already exists
        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'danger')
            return render_template('register.html')

        # Create user
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['user_name'] = user.name
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password.', 'danger')
            return render_template('login.html')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ─────────────────────────── Main Route ───────────────────────────

@app.route('/')
@login_required
def index():
    return render_template('index.html', user_name=session.get('user_name', ''))


# ─────────────────────────── API Routes ───────────────────────────

@app.route('/api/transactions', methods=['GET'])
@api_login_required
def get_transactions():
    try:
        user_id = session['user_id']
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        transaction_type = request.args.get('type')
        category = request.args.get('category')
        date_filter = request.args.get('date')

        query = Transaction.query.filter_by(user_id=user_id)

        if transaction_type:
            query = query.filter(Transaction.type == transaction_type)
        if category:
            query = query.filter(Transaction.category == category)
        if date_filter:
            try:
                filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
                query = query.filter(Transaction.date == filter_date)
            except ValueError:
                pass

        query = query.order_by(Transaction.date.desc(), Transaction.created_at.desc())

        transactions = query.paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'transactions': [t.to_dict() for t in transactions.items],
            'total': transactions.total,
            'pages': transactions.pages,
            'current_page': page
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/transactions', methods=['POST'])
@api_login_required
def add_transaction():
    try:
        user_id = session['user_id']
        data = request.get_json()

        required_fields = ['type', 'amount', 'category', 'description', 'date']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        if data['type'] not in ['income', 'expense']:
            return jsonify({'error': 'Invalid transaction type'}), 400

        try:
            transaction_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

        transaction = Transaction(
            user_id=user_id,
            type=data['type'],
            amount=Decimal(str(data['amount'])),
            category=data['category'],
            description=data['description'],
            date=transaction_date
        )

        db.session.add(transaction)
        db.session.commit()

        return jsonify({
            'message': 'Transaction added successfully',
            'transaction': transaction.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/transactions/<int:transaction_id>', methods=['PUT'])
@api_login_required
def update_transaction(transaction_id):
    try:
        user_id = session['user_id']
        transaction = Transaction.query.filter_by(id=transaction_id, user_id=user_id).first_or_404()
        data = request.get_json()

        if 'type' in data:
            if data['type'] not in ['income', 'expense']:
                return jsonify({'error': 'Invalid transaction type'}), 400
            transaction.type = data['type']
        if 'amount' in data:
            transaction.amount = Decimal(str(data['amount']))
        if 'category' in data:
            transaction.category = data['category']
        if 'description' in data:
            transaction.description = data['description']
        if 'date' in data:
            try:
                transaction.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

        db.session.commit()

        return jsonify({
            'message': 'Transaction updated successfully',
            'transaction': transaction.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/transactions/<int:transaction_id>', methods=['DELETE'])
@api_login_required
def delete_transaction(transaction_id):
    try:
        user_id = session['user_id']
        transaction = Transaction.query.filter_by(id=transaction_id, user_id=user_id).first_or_404()
        db.session.delete(transaction)
        db.session.commit()
        return jsonify({'message': 'Transaction deleted successfully'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/categories', methods=['GET'])
@api_login_required
def get_categories():
    try:
        categories = Category.query.all()
        result = {
            'income': [c.to_dict() for c in categories if c.type == 'income'],
            'expense': [c.to_dict() for c in categories if c.type == 'expense']
        }
        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/categories', methods=['POST'])
@api_login_required
def add_category():
    try:
        data = request.get_json()

        if 'name' not in data or 'type' not in data:
            return jsonify({'error': 'Missing required fields: name, type'}), 400
        if data['type'] not in ['income', 'expense']:
            return jsonify({'error': 'Invalid category type'}), 400

        existing = Category.query.filter_by(name=data['name'], type=data['type']).first()
        if existing:
            return jsonify({'error': 'Category already exists'}), 400

        category = Category(name=data['name'], type=data['type'])
        db.session.add(category)
        db.session.commit()

        return jsonify({
            'message': 'Category added successfully',
            'category': category.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/dashboard', methods=['GET'])
@api_login_required
def get_dashboard_data():
    try:
        user_id = session['user_id']
        transactions = Transaction.query.filter_by(user_id=user_id).all()

        total_income = sum(t.amount for t in transactions if t.type == 'income')
        total_expenses = sum(t.amount for t in transactions if t.type == 'expense')
        balance = total_income - total_expenses

        current_month = datetime.now().month
        current_year = datetime.now().year

        monthly_transactions = [
            t for t in transactions
            if t.date.month == current_month and t.date.year == current_year
        ]

        monthly_income = sum(t.amount for t in monthly_transactions if t.type == 'income')
        monthly_expenses = sum(t.amount for t in monthly_transactions if t.type == 'expense')
        monthly_balance = monthly_income - monthly_expenses

        expense_categories = {}
        for t in transactions:
            if t.type == 'expense':
                expense_categories[t.category] = expense_categories.get(t.category, 0) + float(t.amount)

        monthly_trends = {}
        for i in range(6):
            month = (current_month - i - 1) % 12 + 1
            year = current_year if current_month - i > 0 else current_year - 1
            month_transactions = [
                t for t in transactions
                if t.date.month == month and t.date.year == year
            ]
            month_key = f"{year}-{month:02d}"
            monthly_trends[month_key] = {
                'income': float(sum(t.amount for t in month_transactions if t.type == 'income')),
                'expense': float(sum(t.amount for t in month_transactions if t.type == 'expense'))
            }

        return jsonify({
            'totals': {
                'income': float(total_income),
                'expenses': float(total_expenses),
                'balance': float(balance)
            },
            'monthly': {
                'income': float(monthly_income),
                'expenses': float(monthly_expenses),
                'balance': float(monthly_balance)
            },
            'expense_categories': expense_categories,
            'monthly_trends': monthly_trends,
            'recent_transactions': [
                t.to_dict() for t in
                Transaction.query.filter_by(user_id=user_id)
                    .order_by(Transaction.date.desc()).limit(5).all()
            ]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reports/monthly', methods=['GET'])
@api_login_required
def get_monthly_report():
    try:
        user_id = session['user_id']
        year = request.args.get('year', datetime.now().year, type=int)

        monthly_data = {}
        for month in range(1, 13):
            transactions = Transaction.query.filter(
                Transaction.user_id == user_id,
                db.extract('month', Transaction.date) == month,
                db.extract('year', Transaction.date) == year
            ).all()

            income = sum(t.amount for t in transactions if t.type == 'income')
            expenses = sum(t.amount for t in transactions if t.type == 'expense')

            monthly_data[f"{year}-{month:02d}"] = {
                'income': float(income),
                'expenses': float(expenses),
                'balance': float(income - expenses)
            }

        return jsonify(monthly_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reports/category', methods=['GET'])
@api_login_required
def get_category_report():
    try:
        user_id = session['user_id']
        transaction_type = request.args.get('type', 'expense')

        if transaction_type not in ['income', 'expense']:
            return jsonify({'error': 'Invalid transaction type'}), 400

        transactions = Transaction.query.filter_by(user_id=user_id, type=transaction_type).all()

        category_data = {}
        for transaction in transactions:
            category = transaction.category
            if category not in category_data:
                category_data[category] = {'total': 0, 'count': 0, 'transactions': []}
            category_data[category]['total'] += float(transaction.amount)
            category_data[category]['count'] += 1
            category_data[category]['transactions'].append(transaction.to_dict())

        return jsonify(category_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/budgets', methods=['GET'])
@api_login_required
def get_budgets():
    try:
        user_id = session['user_id']
        month = request.args.get('month', datetime.now().month, type=int)
        year = request.args.get('year', datetime.now().year, type=int)

        budgets = Budget.query.filter_by(user_id=user_id, month=month, year=year).all()

        budget_data = []
        for budget in budgets:
            actual_spending = db.session.query(db.func.sum(Transaction.amount)).filter(
                Transaction.user_id == user_id,
                Transaction.category == budget.category,
                Transaction.type == 'expense',
                db.extract('month', Transaction.date) == month,
                db.extract('year', Transaction.date) == year
            ).scalar() or 0

            budget_info = budget.to_dict()
            budget_info['actual'] = float(actual_spending)
            budget_info['remaining'] = float(budget.amount - actual_spending)
            budget_info['percentage'] = (float(actual_spending) / float(budget.amount)) * 100 if budget.amount > 0 else 0
            budget_data.append(budget_info)

        return jsonify(budget_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/budgets', methods=['POST'])
@api_login_required
def add_budget():
    try:
        user_id = session['user_id']
        data = request.get_json()

        required_fields = ['category', 'amount', 'month', 'year']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        existing = Budget.query.filter_by(
            user_id=user_id,
            category=data['category'],
            month=data['month'],
            year=data['year']
        ).first()

        if existing:
            return jsonify({'error': 'Budget already exists for this category and period'}), 400

        budget = Budget(
            user_id=user_id,
            category=data['category'],
            amount=Decimal(str(data['amount'])),
            month=data['month'],
            year=data['year']
        )

        db.session.add(budget)
        db.session.commit()

        return jsonify({
            'message': 'Budget added successfully',
            'budget': budget.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ─────────────────────────── Error Handlers ───────────────────────────

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
