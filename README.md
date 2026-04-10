# Safe Zone Check Service

FastAPI service that checks whether text in an image falls within the safe zone for Meta ads.

## Safe Zone Boundaries
- Top: 14% from top edge
- Bottom: 20% from bottom edge  
- Left: 6% from left edge
- Right: 6% from right edge

## Deployment (Railway)

1. Create a new Railway service from this repo/directory
2. Railway will use the Dockerfile automatically
3. Set environment variable (optional): `SERVICE_API_KEY=your_secret_key`
4. Note the deployed URL (e.g. `https://safezone-check-production.up.railway.app`)

## API

### POST /check-safezone

**Request:**
```json
{
  "file_id": "1UUmT92SNkhaKtyCqrubGSVvNS8-vZQ23",
  "file_name": "my_image.jpg"
}
```

**Response (passed):**
```json
{
  "ok": true,
  "file_id": "1UUmT92...",
  "file_name": "my_image.jpg",
  "passed": true,
  "violations": [],
  "message": "✅ my_image.jpg passed safe zone check."
}
```

**Response (violation):**
```json
{
  "ok": true,
  "file_id": "1UUmT92...",
  "file_name": "my_image.jpg",
  "passed": false,
  "violations": [
    {
      "text": "Vor 8 Wochen:",
      "confidence": 0.92,
      "zone": "top 14%",
      "position": {"x_min": 120, "y_min": 45, "x_max": 380, "y_max": 98}
    }
  ],
  "message": "⚠️ Safe zone violation in *my_image.jpg*: Text found outside safe zone — 'Vor 8 Wochen:' (top 14%)"
}
```

### Headers
- `X-API-Key: your_secret_key` (if SERVICE_API_KEY is set)

## Make.com Integration

Add an **HTTP module** after the BILD ANALYSE module (image branch only):

**Module:** HTTP - Make a request  
**URL:** `https://your-service.up.railway.app/check-safezone`  
**Method:** POST  
**Headers:** `X-API-Key: your_secret_key`  
**Body type:** Raw  
**Content type:** JSON  
**Body:**
```json
{
  "file_id": "{{59.output_fileid}}",
  "file_name": "{{59.output_filename}}"
}
```

Then add a **Router** after it:
- **Branch 1** (filter: `response.passed = false`) → Slack message with `response.message`
- **Branch 2** (no filter) → continue workflow
# check-safezone
