import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL',
                                        'mssql+pyodbc://dev_josh:reubenjoshua10@EPRIME-RJP/SplitterDB?driver=ODBC+Driver+17+for+SQL+Server')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 3600,
        'pool_size': 10,
        'max_overflow': 20,
        'connect_args': {
            'timeout': 30,
            'autocommit': True
        }
    }

    # Upload configuration
    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 1024 * 1024 * 1024  # 1GB in bytes

    # Session configuration
    PERMANENT_SESSION_LIFETIME = 1800  # 30 minutes
    SEND_FILE_MAX_AGE_DEFAULT = 1800  # 30 minutes