# API Overview

Invoice Manager provides a full REST API for integration with other systems.

## Base URL

```
http://your-server:5000/api/v1
```

## Authentication

All API requests require authentication using an API key.

### Getting an API Key

1. Log in to Invoice Manager
2. Go to **Settings → API Keys**
3. Click **Generate New API Key**
4. Copy and securely store your key

!!! warning "Keep Your Key Secret"
    API keys provide full access to your data. Never share them publicly.

### Using the API Key

Include your API key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key" \
     https://your-server/api/v1/customers
```

## Response Format

All responses are JSON formatted:

```json
{
  "success": true,
  "data": { ... }
}
```

Error responses:

```json
{
  "success": false,
  "error": "Error message"
}
```

## HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 401 | Unauthorized |
| 404 | Not Found |
| 500 | Server Error |

## Available Endpoints

### Customers

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/customers` | List all customers |
| GET | `/customers/{id}` | Get a customer |
| POST | `/customers` | Create a customer |
| PUT | `/customers/{id}` | Update a customer |
| DELETE | `/customers/{id}` | Delete a customer |

### Products

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/products` | List all products |
| GET | `/products/{id}` | Get a product |
| POST | `/products` | Create a product |
| PUT | `/products/{id}` | Update a product |
| DELETE | `/products/{id}` | Delete a product |

### Invoices

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/invoices` | List all invoices |
| GET | `/invoices/{id}` | Get an invoice |
| POST | `/invoices` | Create an invoice |
| PUT | `/invoices/{id}` | Update an invoice |
| DELETE | `/invoices/{id}` | Delete an invoice |
| POST | `/invoices/{id}/send` | Send invoice email |
| GET | `/invoices/{id}/pdf` | Download PDF |

## Rate Limiting

API requests are limited to:

- 100 requests per minute
- 1000 requests per hour

## Webhooks

Receive real-time notifications when events occur. See [Webhooks](webhooks.md) for details.

## Need Help?

📧 **Email**: [helpdesk@sondelaconsulting.com](mailto:helpdesk@sondelaconsulting.com)
