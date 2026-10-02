# E-Commerce Order Management & Search Service

## Overview

This project is a polyglot-persistence based E-Commerce Order Management and Search Service built with Vue 3, Vite, FastAPI, PostgreSQL, MongoDB, Elasticsearch, RabbitMQ, and Celery. The system separates transactional order data, flexible product catalog data, and high-performance search data across specialized storage systems.

PostgreSQL acts as the source of truth for users, orders, order items, money, product snapshots, and fulfillment status. MongoDB manages the flexible product catalog, while Elasticsearch stores a searchable projection of orders for fast admin search, filtering, and aggregations. RabbitMQ and Celery provide asynchronous synchronization between PostgreSQL and Elasticsearch.

## Main Features

### Customer / Storefront
- Product browsing
- Product catalog retrieved from MongoDB
- Product details
- Shopping cart
- Checkout
- Order creation
- Historical order information
- Customer workspace/login interface

### Admin
- Admin workspace/login interface
- Order search
- Full-text order search
- Order filtering
- Order status management
- Order details
- Search aggregations
- Product catalog administration
- Product creation, editing, and deletion

## Technology Stack

### Frontend
- Vue 3
- Vite
- JavaScript
- Vue Router
- Pinia
- Custom CSS/UI components

### Backend
- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic
- Async database clients

### Data Stores
- PostgreSQL 16
- MongoDB 7
- Elasticsearch 8.x

### Asynchronous Processing
- RabbitMQ
- Celery

### Infrastructure
- Docker
- Docker Compose
- WSL2 / Ubuntu for local development

## Architecture

```text
                         Vue 3 + Vite
                              |
                              | REST API
                              v
                         FastAPI Backend
                              |
                 +------------+-------------+
                 |                          |
                 v                          v
            PostgreSQL                  MongoDB
          Source of Truth            Product Catalog
                 |
                 | PostgreSQL Commit
                 v
               Outbox
                 |
                 v
             RabbitMQ
                 |
                 v
          Celery Worker
                 |
                 | Build canonical
                 | order projection
                 v
          Elasticsearch
                 |
                 v
          Admin Order Search
