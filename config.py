import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'mysql://uaeguuzfslfjcllx:ZBWIQgMLcrzGEsTw17Wq@bgqrmxzfrkb96jbracha-mysql.services.clever-cloud.com:3306/bgqrmxzfrkb96jbracha'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
