from agira.settings import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Disable static files handling for tests
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
