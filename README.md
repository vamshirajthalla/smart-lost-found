# Campus Lost & Found Smart Box

> Cloud Computing project: Product No. 50, Team Null Pointers, Batch 04 (SR University)

A full-stack IoT project: an ESP32 + RFID box logs item check-in/check-out
by tag scan, state lives in DynamoDB, and a web dashboard (hosted on S3)
shows what's currently in the box. An OLED on the box itself confirms
every scan.

## Architecture

```
   ┌─────────────┐   MQTT/TLS   ┌────────────────┐   IoT Rule   ┌───────────────────┐
   │  ESP32 box  │ ───────────▶ │  AWS IoT Core   │ ───────────▶ │ ingest_handler.py  │
   │ RFID + OLED │ ◀─────────── │  (MQTT broker)  │              │     (Lambda)       │
   └─────────────┘  status topic└────────────────┘              └─────────┬──────────┘
                                                                            │
                                                                     read/write
                                                                            ▼
                                                                  ┌──────────────────┐
                                                                  │    DynamoDB      │
                                                                  │  LostFoundItems  │
                                                                  └────────┬─────────┘
                                                                           │
                                                                     read/write
                                                                           ▼
   ┌─────────────┐   HTTPS      ┌────────────────┐            ┌────────────────────┐
   │  S3 static  │ ───────────▶ │   API Gateway   │ ─────────▶ │  api_handler.py     │
   │  dashboard  │ ◀─────────── │  (HTTP API)     │            │     (Lambda)        │
   └─────────────┘              └────────────────┘            └────────────────────┘
```

**Flow:** a student drops an item and taps its RFID tag on the box. The
ESP32 publishes a scan event over MQTT. `ingest_handler` looks the tag up
in DynamoDB, toggles its status (unseen tag → new "unidentified item"
record; known tag → flips CHECKED_IN/CHECKED_OUT), and publishes the
result back to the box so the OLED can confirm it. Staff use the web
dashboard to see what's in the box and mark items claimed when an owner
picks them up in person. Naming items and adding descriptions is done
through the `PUT /items/{itemId}` API (see API reference); a dashboard
form for this is a planned improvement.

## Repo layout

```
firmware/            ESP32 Arduino sketch + secrets template
lambda/               ingest_handler.py (IoT -> DynamoDB), api_handler.py (REST API)
infrastructure/       SAM template, IoT policy, deploy script, custom resource
frontend/             Single-file S3 dashboard (index.html)
```

## 1. Deploy the AWS backend

Requirements: AWS CLI v2 (configured with credentials, or AWS CloudShell), [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html), Python 3.12.

```bash
cd infrastructure
chmod +x deploy.sh
./deploy.sh
```

**AWS Academy Learner Lab:** run this from CloudShell in `us-east-1`. Learner
Lab blocks creating IAM roles, so if the stack fails with an IAM error, add
`Role: !Sub "arn:aws:iam::${AWS::AccountId}:role/LabRole"` to each function in
`template.yaml` and remove their `Policies:` blocks. Learner Lab credentials
expire when the session ends, so redeploy or refresh them each session.

This will:
1. Build and deploy the SAM stack: DynamoDB table (`ItemsTable` with a
   `StatusIndex` GSI for fast "what's currently in the box" queries), the
   two Lambdas, the IoT topic rule, the HTTP API, and the S3 bucket.
2. Create an IoT Thing (`smartbox-box-01` by default), generate a
   certificate/key pair, attach a policy scoped to that box's topics only,
   and download the Amazon Root CA.
3. Print the API URL, frontend bucket name, and the cert file locations
   you'll need next.

Run it again with `BOX_ID=box-02 ./deploy.sh` to provision additional
physical boxes against the same stack — each gets its own Thing,
certificate, and topic namespace (`lostfound/box-02/...`), so one backend
supports as many drop boxes as you want.

## 2. Flash the ESP32

1. In the Arduino IDE, install: `MFRC522`, `Adafruit SSD1306`,
   `Adafruit GFX`, `PubSubClient`, `ArduinoJson`.
2. Wire the RC522 and SSD1306 as described at the top of
   `firmware/smart_box_esp32.ino`.
3. Copy `firmware/secrets_template.h` → `firmware/secrets.h` and fill in:
   - Your Wi-Fi SSID/password
   - `AWS_IOT_ENDPOINT` (printed by `deploy.sh`)
   - The contents of the three cert files from `infrastructure/certs/<box-id>/`
4. If this is a second box, change `BOX_ID` at the top of the `.ino` file
   to match what you passed to `deploy.sh`.
5. Upload to the ESP32.

## 3. Publish the dashboard

1. Open `frontend/index.html` and set `CONFIG.apiBase` to the `ApiUrl`
   stack output (no trailing slash).
2. Upload it to the frontend bucket:
   ```bash
   aws s3 cp frontend/index.html s3://<FrontendBucketName>/index.html
   ```
3. Open the `FrontendUrl` stack output in a browser.

The dashboard works without step 1 too — it falls back to sample data
and shows a small banner so you can preview the UI before the backend
is wired up.

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/items` | List items. Optional `?status=CHECKED_IN` or `CHECKED_OUT`. |
| GET | `/items/{itemId}` | Get one item. |
| PUT | `/items/{itemId}` | Update `itemName`, `description`, or `ownerContact`. |
| POST | `/items/{itemId}/claim` | Mark an item claimed (staff hands it back without a rescan). Body: `{"ownerContact": "..."}` (optional). |

## MQTT topics

| Topic | Direction | Payload |
|---|---|---|
| `lostfound/<boxId>/scan` | device → cloud | `{"itemId": "<tagUID>", "boxId": "<boxId>", "ts": <epoch>}` |
| `lostfound/<boxId>/status` | cloud → device | `{"itemId": "...", "itemName": "...", "action": "checked_in"\|"checked_out", "ts": "..."}` |

## Notes & next steps

- **Secrets:** never commit `firmware/secrets.h` or anything in
  `infrastructure/certs/` (both are in `.gitignore`). If a private key is
  ever pushed, delete that certificate in AWS IoT and issue a new one.
- **Security:** each box's certificate is scoped (via `iot-policy.json`)
  to only publish/subscribe on its own `lostfound/<boxId>/*` topics. The
  dashboard API currently has no authentication, which is fine for a demo
  but should be fixed (e.g. Cognito or an API key) before real use.
- **Cost:** everything here is pay-per-request (DynamoDB on-demand, Lambda,
  HTTP API) — idle cost is close to zero.
- **Ideas to extend:** email/SMS the owner automatically once staff add a
  contact (SNS), a photo upload step when staff first identify an item
  (S3 + presigned URL), or a "days in box" alert that flags items for
  campus security to donate/dispose of after a retention period.
