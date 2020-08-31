# -*- coding: utf-8 -*-
from __future__ import absolute_import
import logging
import redis
from redis.exceptions import LockError
from functools import wraps
from dbaas.settings import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD
from celery import task
from celery.five import monotonic
from celery.utils.log import get_task_logger
from contextlib import contextmanager
from django.core.cache import cache
from hashlib import md5


LOG = logging.getLogger(__name__)


REDIS_CLIENT = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD
)
LOCK_EXPIRE = 60 * 10  # Lock expires in 10 minutes


def only_one(key="", timeout=None):
    """Enforce only one celery task at a time."""
    def real_decorator(function):
        """Decorator."""
        @wraps(function)
        def wrapper(*args, **kwargs):
            """Caller."""
            have_lock = False
            lock = REDIS_CLIENT.lock(key, timeout=timeout)
            try:
                have_lock = lock.acquire(blocking=False)
                if have_lock:
                    function(*args, **kwargs)
                else:
                    LOG.info("key %s locked..." % key)
            finally:
                if have_lock:
                    try:
                        lock.release()
                    except LockError:
                        pass
        return wrapper
    return real_decorator


@contextmanager
def memcache_lock(lock_id, oid):
    timeout_at = monotonic() + LOCK_EXPIRE - 3
    # cache.add fails if the key already exists
    status = cache.add(lock_id, oid, LOCK_EXPIRE)
    try:
        yield status
    finally:
        # memcache delete is very slow, but we have to use it to take
        # advantage of using add() for atomic locking
        if monotonic() < timeout_at and status:
            # don't release the lock if we exceeded the timeout
            # to lessen the chance of releasing an expired lock
            # owned by someone else
            # also don't release the lock if we didn't acquire it
            cache.delete(lock_id)


def lock_execution(key=""):
    """Enforce only one celery task at a time."""
    def real_decorator(function):
        """Decorator."""
        @wraps(function)
        def wrapper(*args, **kwargs):
            """Caller."""
            self = args[0]
            from celery.contrib import rdb;rdb.set_trace()
            hexdigest = md5(key).hexdigest()
            lock_id = '{0}-lock-{1}'.format(self.name, hexdigest)
            LOG.debug('lock id creeated: {}'.format(lock_id))
            with memcache_lock(lock_id, self.app.oid) as acquired:
                if acquired:
                    return function(*args, **kwargs)
            LOG.debug(
                'Task with key {} is already running by another worker', key
            )
        return wrapper
    return real_decorator



# @task(bind=True)
# def import_feed(self, feed_url):
#     # The cache key consists of the task name and the MD5 digest
#     # of the feed URL.
#     feed_url_hexdigest = md5(feed_url).hexdigest()
#     lock_id = '{0}-lock-{1}'.format(self.name, feed_url_hexdigest)
#     logger.debug('Importing feed: %s', feed_url)
#     with memcache_lock(lock_id, self.app.oid) as acquired:
#         if acquired:
#             return Feed.objects.import_feed(feed_url).url
#     logger.debug(
#         'Feed %s is already being imported by another worker', feed_url)