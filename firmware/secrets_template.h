/*
 * Copy this file to secrets.h (same folder) and fill in your values.
 * secrets.h is where real credentials live — never commit it to git.
 * Add "secrets.h" to your .gitignore.
 */

#ifndef SECRETS_H
#define SECRETS_H

// ---- Wi-Fi ----
#define WIFI_SSID       "YOUR_WIFI_SSID"
#define WIFI_PASSWORD   "YOUR_WIFI_PASSWORD"

// ---- AWS IoT Core ----
// Get this with: aws iot describe-endpoint --endpoint-type iot:Data-ATS
#define AWS_IOT_ENDPOINT  "xxxxxxxxxxxxx-ats.iot.us-east-1.amazonaws.com"

// Paste the contents of AmazonRootCA1.pem, <thing>-certificate.pem.crt,
// and <thing>-private.pem.key here (produced by infrastructure/deploy.sh).

static const char AWS_ROOT_CA1[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
PASTE_AMAZON_ROOT_CA1_HERE
-----END CERTIFICATE-----
)EOF";

static const char AWS_CERT_CRT[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
PASTE_DEVICE_CERTIFICATE_HERE
-----END CERTIFICATE-----
)EOF";

static const char AWS_CERT_PRIVATE[] PROGMEM = R"EOF(
-----BEGIN RSA PRIVATE KEY-----
PASTE_DEVICE_PRIVATE_KEY_HERE
-----END RSA PRIVATE KEY-----
)EOF";

#endif
