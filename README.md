# Mobile Network Auto-Refill Bots (Lidl Connect & ALDI TALK)

## Overview
A collection of Python Selenium automation scripts that automatically log into the customer portals for **Lidl Connect** and **ALDI TALK** to check your remaining data balance and trigger a data refill or booking when necessary.

These tools are especially useful for managing data plans that offer auto-refillable or recurring data benefits, ensuring you never run out of high-speed internet.

## Features

### Lidl Connect Bot (`lidl.py`)
- **Automated Login**: Uses Selenium to inject credentials and log into the portal (`kundenkonto.lidl-connect.de`).
- **Data Parsing**: Scrapes the dashboard to determine remaining data.
- **Automatic Refill**: Automatically clicks the refill button if the remaining balance drops to **0.9 GB or below**.

### ALDI TALK Bot (`aldi.py`)
- **Automated Login**: Logs into the ALDI TALK Kundenportal (CIAM) using complex shadow DOM traversal.
- **Cookie Handling**: Automatically handles and accepts the Usercentrics cookie wall.
- **Data Parsing**: Uses Javascript and DOM parsing to extract your remaining data balance.
- **Automatic Booking**: Can automatically book a 1 GB add-on if the `AUTO_BOOK_1GB` environment variable is enabled.

### Shared Features
- **Headless Execution**: Both bots fully support headless Chrome mode for operation on headless servers (like GitHub Actions runners or VPS).
- **GitHub Actions Integration**: Includes a pre-configured, schedule-based GitHub Actions workflow for Lidl (which can be extended for Aldi).
- **Error Handling & Debugging**: Automatically captures screenshots and HTML page sources to `/tmp/` upon failure, ensuring easier troubleshooting.

## Requirements
- Python 3.10+
- Google Chrome browser installed
- ChromeDriver (compatible with your installed Chrome version, or rely on automatic detection/setup)

## Installation

1. Clone or download the repository to your local machine.
2. Install the required Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration 

The scripts use environment variables for configuration. You must set the necessary credentials before running either script.

### Environment Variables for Lidl Connect (`lidl.py`)

| Variable | Description | Default | Required? |
| :--- | :--- | :--- | :--- |
| `LIDL_USERNAME` | Your Lidl Connect username (typically your MSISDN / phone number). | - | **Yes** |
| `LIDL_PASSWORD` | Your Lidl Connect account password. | - | **Yes** |
| `HEADLESS` | Run Chrome in headless mode. Set to `false` if you want to watch the execution. | `true` | No |
| `WAIT_SECS` | Maximum wait time (in seconds) for web elements to load on the page. | `40` | No |

### Environment Variables for ALDI TALK (`aldi.py`)

| Variable | Description | Default | Required? |
| :--- | :--- | :--- | :--- |
| `ALDI_RUFNUMMER` | Your ALDI TALK phone number. | - | **Yes** |
| `ALDI_PASSWORT` | Your ALDI TALK password. | - | **Yes** |
| `ALDI_LOGIN_URL` | The login URL for ALDI TALK portal. | Provided URL | No |
| `HEADLESS` | Run Chrome in headless mode. Use `0`, `false` or `1`, `true`. | `0` (false) | No |
| `AUTO_BOOK_1GB` | Set to `1` or `true` to automatically click the 1 GB booking button. | `false` | No |
| `WAIT_SECS` | Maximum wait time (in seconds) for web elements to load on the page. | `25` | No |

## Usage

### Running Locally

You can run the scripts manually from your terminal / command prompt.

**Lidl Connect (Linux / macOS):**
```bash
export LIDL_USERNAME="your-phone-number"
export LIDL_PASSWORD="your-password"
python lidl.py
```

**ALDI TALK (Linux / macOS):**
```bash
export ALDI_RUFNUMMER="your-phone-number"
export ALDI_PASSWORT="your-password"
export HEADLESS="false"
export AUTO_BOOK_1GB="true"
python aldi.py
```

*(For Windows, use `$env:VARIABLE_NAME="value"` in PowerShell instead of `export`)*

### Running on GitHub Actions (Recommended)

A GitHub Actions workflow is provided in `.github/workflows/lidl.yml` to run the Lidl script systematically in the cloud. You can adapt it or copy it to create one for ALDI TALK.

1. In your GitHub repository, navigate to **Settings** > **Secrets and variables** > **Actions**.
2. Click **New repository secret** and add your credentials (e.g., `LIDL_USERNAME`, `LIDL_PASSWORD`, `ALDI_RUFNUMMER`, `ALDI_PASSWORT`).
3. Uncomment the code in `.github/workflows/lidl.yml`. Use the `cron` schedule configuration to determine how frequently the bot should run.
4. Commit and push the changes.

## Troubleshooting
If a bot fails, it generates debugging artifacts:
- `screen.png`: A screenshot of where the bot failed.
- `page.html`: The HTML source code of the page at the time of failure.

These are saved in the `/tmp/lidl/` or `/tmp/alditalk/` directory.

## Disclaimer & Legal
This project is an independent effort and is **not** affiliated with, maintained, authorized, endorsed, or sponsored by Lidl Connect, ALDI TALK, or related entities. 
- Use these scripts at your own risk. 
- Automated interaction with the web portal may violate the Terms of Service of your provider. 
- Please be considerate of the server loads, and avoid scheduling the scripts so frequently that it mimics a DDoS attack.
