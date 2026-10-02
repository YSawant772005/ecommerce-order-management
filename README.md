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
Database Responsibilities
PostgreSQL

PostgreSQL is the authoritative transactional database.

It stores:

Users
Orders
Order items
Order totals
Product title snapshots
Product price snapshots
Order status
Fulfillment-related information

Orders and money-related data are kept in PostgreSQL because they require transactional consistency.

MongoDB

MongoDB stores the current product catalog.

Product documents support flexible fields such as:

{
  "sku": "WM-001",
  "title": "Wireless Mouse",
  "description": "Ergonomic wireless mouse",
  "price": 899,
  "category": "Accessories",
  "tags": ["wireless", "mouse"],
  "attributes": {
    "color": "black",
    "dpi": 1600
  },
  "variants": [],
  "active": true
}

MongoDB is used for catalog operations because product documents can contain nested and variable attributes.

Elasticsearch

Elasticsearch is used as a derived search projection for admin order search.

It supports:

Full-text search
Multi-field search
Filtering
Date ranges
Status filtering
Terms aggregations
Sum aggregations

Elasticsearch is not the source of truth for orders.

Checkout Flow

When a customer places an order:

Customer
   |
   v
Vue Checkout
   |
   v
FastAPI
   |
   v
MongoDB
Validate current product title + price
   |
   v
PostgreSQL Transaction
   |
   +--> orders
   |
   +--> order_items
   |
   +--> immutable product snapshots
   |
   v
COMMIT
   |
   v
Outbox / Queue
   |
   v
RabbitMQ
   |
   v
Celery Worker
   |
   v
Elasticsearch

Before an order is created, the backend reads the current product information from MongoDB. The title and price used during checkout are then stored as immutable snapshots in PostgreSQL.

For example, if a product was purchased for ₹899, changing the catalog price later to ₹1,099 does not change the historical order. The order continues to show the original title and price.

Elasticsearch Synchronization

The project implements Strategy 1: asynchronous dual-write synchronization.

The synchronization process is:

PostgreSQL
    |
    | Commit first
    v
RabbitMQ
    |
    v
Celery Worker
    |
    v
Elasticsearch

PostgreSQL is committed before Elasticsearch is updated. Therefore, there can be a short eventual-consistency window in which PostgreSQL contains the latest order while Elasticsearch has not yet received the updated projection.

RabbitMQ acts as the message broker and Celery performs the background synchronization work.

The system does not treat Elasticsearch as the authoritative order database.

Canonical Order Projection

The backend uses a canonical order projection function, build_order_document, to construct the Elasticsearch representation from PostgreSQL order data.

Conceptually:

PostgreSQL Order
       |
       v
build_order_document()
       |
       v
Elasticsearch Order Document

This provides a consistent representation whenever an order needs to be indexed or reindexed.

Order Search

The admin search interface communicates with Elasticsearch rather than directly querying PostgreSQL for search operations.

Example endpoint:

POST /api/search/orders

The search functionality supports:

Text search
Order/customer search
Status filtering
Date filtering
Total/range filtering
Terms aggregations
Sum aggregations
Order Details and Status

Individual order details are retrieved from PostgreSQL because PostgreSQL is the source of truth.

GET /api/orders/{order_id}

When an administrator changes an order status:

PATCH /api/orders/{order_id}/status

the status is updated in PostgreSQL first and then synchronized asynchronously to Elasticsearch.

Catalog Administration

Product catalog operations are handled through MongoDB.

Typical operations include:

GET    /api/products
POST   /api/products
GET    /api/products/{product_id}
PATCH  /api/products/{product_id}
DELETE /api/products/{product_id}

Catalog changes affect the current product catalog but do not modify historical order snapshots stored in PostgreSQL.

Project Structure
ecommerce-order-management/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── repositories/
│   │   ├── services/
│   │   └── workers/
│   │
│   ├── scripts/
│   ├── sql/
│   ├── tests/
│   ├── requirements.txt
│   └── pyproject.toml
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── stores/
│   │   └── views/
│   ├── package.json
│   └── vite.config.js
│
├── docs/
├── deploy/
├── docker-compose.yml
├── README.md
├── NOTES.md
└── .env.example
Running the Project
Prerequisites

Install:

Python 3.11+
Node.js and npm
Docker Desktop
WSL2 / Ubuntu
Git
Start Infrastructure

From the project root:

docker compose up -d

Check running services:

docker compose ps

The infrastructure includes:

PostgreSQL
MongoDB
Elasticsearch
RabbitMQ
Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

Start FastAPI:

uvicorn app.main:app --host 0.0.0.0 --port 8000

Backend:

http://localhost:8000

Health check:

GET /api/health
Celery Worker

In another terminal:

cd backend
source .venv/bin/activate
celery -A app.workers.celery_app:celery_app worker --loglevel=info --pool=solo --concurrency=1

The worker processes asynchronous synchronization tasks through RabbitMQ.

Frontend

In another terminal:

cd frontend
npm install
npm run dev -- --host 0.0.0.0

Frontend:

http://localhost:5173
Seed Data

The project provides deterministic synthetic seed data for development and demonstration.

Example:

python scripts/seed.py --reset --seed 42 --anchor-date 2026-09-30T00:00:00Z

The seed creates users, products, orders, order items, multiple product categories, different order statuses, and data suitable for demonstrating the search functionality.

Important Data Ownership Rules
Data / Operation	Source
Current product catalog	MongoDB
Product catalog CRUD	MongoDB
Users	PostgreSQL
Orders	PostgreSQL
Order items	PostgreSQL
Order totals	PostgreSQL
Historical product title	PostgreSQL snapshot
Historical product price	PostgreSQL snapshot
Order status	PostgreSQL
Admin order search	Elasticsearch
Search aggregations	Elasticsearch

The core rule is:

PostgreSQL is the source of truth for orders, MongoDB is the source of truth for the current catalog, and Elasticsearch is the derived search projection.

Failure Handling

If Elasticsearch becomes temporarily unavailable, the committed PostgreSQL order remains safe because PostgreSQL is the source of truth.

The synchronization path can be represented as:

Order Created
     |
     v
PostgreSQL COMMIT
     |
     v
Synchronization Job
     |
     +---- Elasticsearch unavailable
     |
     v
Retry / pending synchronization
     |
     v
Elasticsearch available
     |
     v
Order indexed

This demonstrates the difference between transactional persistence and eventual search synchronization.

Testing

Run the backend tests with:

pytest

The tests cover areas such as:

Order creation
Product validation
Money handling
Catalog operations
Elasticsearch search
Synchronization
API behavior
Seed invariants
Example Demonstration Flow
Start PostgreSQL, MongoDB, Elasticsearch, and RabbitMQ using Docker Compose.
Start the FastAPI backend.
Start the Celery worker.
Start the Vue frontend.
Open the storefront.
Browse products stored in MongoDB.
Add products to the cart.
Complete checkout.
Validate that the order is stored in PostgreSQL.
Observe the RabbitMQ/Celery synchronization.
Verify that the order is indexed in Elasticsearch.
Search for the order from the admin search interface.
Open the order details.
Change the order status.
Verify the PostgreSQL update.
Verify that Elasticsearch receives the updated projection.
Modify a product in MongoDB.
Verify that historical order title and price snapshots remain unchanged.
Key Architectural Concepts Demonstrated

This project demonstrates:

Polyglot persistence
Transactional database design
PostgreSQL source-of-truth architecture
MongoDB document modeling
Elasticsearch search projections
Full-text search
Eventual consistency
Asynchronous processing
RabbitMQ message brokering
Celery background workers
Outbox-based synchronization safety
Canonical data projections
Immutable order snapshots
Database ownership boundaries
FastAPI REST APIs
Vue.js SPA architecture
Docker Compose
Deterministic synthetic data generation
UI / Frontend Design

The frontend uses Vue 3 and Vite with a custom premium e-commerce visual design. The customer-facing interface uses an editorial/lifestyle-inspired layout with a dark green, warm cream, and peach color palette, strong typography, generous whitespace, and responsive layouts. The application also separates shopper and admin workspace experiences and provides dedicated views for storefront, checkout, order details, admin search, and catalog administration.

Conclusion

The project demonstrates how an e-commerce application can combine multiple specialized persistence technologies without treating them as competing sources of truth. PostgreSQL provides transactional consistency for orders and money, MongoDB provides flexible catalog storage, and Elasticsearch provides fast search and analytics capabilities. RabbitMQ and Celery connect the transactional order system with the asynchronous Elasticsearch indexing pipeline, creating a practical example of polyglot persistence, asynchronous processing, and eventual consistency.
