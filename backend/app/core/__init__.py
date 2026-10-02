"""Infrastructure clients and configuration.

Every store is reached through exactly one module here, which is what makes the
data-source rule structural rather than a convention:

    postgres.py       -> PostgreSQL   (orders, users, outbox)
    mongo.py          -> MongoDB      (product catalog)
    elasticsearch.py  -> Elasticsearch (admin order search projection)
"""
