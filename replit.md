# Overview

This project is a cryptocurrency trading bot designed for automated trading on the ETH/USDT pair with x500 leverage. It utilizes a Parabolic SAR (SAR) indicator strategy across multiple timeframes (1m, 5m, 15m) to generate trading signals. The system includes a Flask-based web dashboard for monitoring and control, real-time Telegram notifications for trade alerts, and a market simulator for testing. The primary goal is to provide an accessible and automated trading solution with a user-friendly interface, including a Telegram Mini Application for on-the-go management.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture
- **Framework**: Vanilla JavaScript with Bootstrap 5
- **Design Pattern**: Single Page Application (SPA) with polling for real-time updates (every 3 seconds)
- **UI Components**: Dark theme trading dashboard with responsive cards, status indicators, current position details, trade entry signals (Level 1/2/3 for SAR indicators), and trade history.
- **Telegram WebApp**: A full-featured clone of the main dashboard, integrated directly into Telegram, offering identical functionality and real-time updates. It bypasses password protection by leveraging Telegram authentication.

## Backend Architecture
- **Framework**: Flask with Python
- **Design Pattern**: Modular architecture separating trading logic, notifications, and web interface.
- **Core Components**:
    - `TradingBot` class: Manages exchange integration/simulation, SAR calculations, and position management.
    - `MarketSimulator` class: Provides realistic market data.
    - `TelegramNotifier` class: Handles Telegram notification delivery.
    - Flask app: Serves the web dashboard and REST API endpoints.
- **Threading Model**: A main Flask thread and a background trading thread ensure continuous market monitoring.

## Trading Strategy
- **Algorithm**: Pure Parabolic SAR strategy (SAR-only, no additional filters).
- **Entry Condition**: A position is opened when 15m SAR direction aligns with 1m SAR direction (for both LONG and SHORT).
- **Exit Condition**: A position is closed when the 1m SAR direction changes.
- **Risk Management**:
    - Position Sizing: 10% of the current balance is used for each trade, dynamically calculated.
    - Leverage: x500 leverage is applied.
    - Trade Duration: Each position has a random close time between 8 to 13 minutes (480-780 seconds).
- **Operating Mode**: Paper trading mode is active with a starting balance of $100.
- **Instrument**: ETH/USDT.

## Data Storage
- **State Persistence**: Bot state, trading history, and configuration are stored in JSON files.
- **In-Memory Storage**: A global state dictionary facilitates real-time data sharing between components.
- **Database**: No external database is used; a file-based approach is employed for simplicity.

## Authentication & Security
- **API Security**: API keys for exchange integration are managed via environment variables.
- **Session Management**: Flask secret key is used for basic session security.
- **Dashboard Control Protection**: A `DASHBOARD_PASSWORD` is required for critical control actions (Start Bot, Stop Bot, Close Position, Delete Last Trade, Reset Balance) on the main web dashboard. The Telegram WebApp bypasses this for Telegram-authenticated users.

# External Dependencies

## Trading Exchange
- **ASCENDEX API**: Used for cryptocurrency exchange integration, primarily with ETH/USDT.
- **ccxt library**: Employed for unified exchange API interaction, market data, and order execution.

## Notification Services
- **Telegram Bot API**: Used for real-time trade notifications and alerts. The bot is **open for everyone** - any user can send `/start` to subscribe and receive trading notifications.
- **Webhook Integration**: Telegram bot uses webhook to receive incoming messages and automatically add new subscribers.
- **Multi-User Support**: Bot maintains a list of all subscribed users and sends notifications to all of them simultaneously.

## Technical Analysis
- **Python TA library**: Utilized for Parabolic SAR indicator calculations.
- **Pandas**: Used for OHLCV (Open, High, Low, Close, Volume) data processing across 1-minute, 5-minute, and 15-minute timeframes.

## Frontend Libraries
- **Bootstrap 5**: Provides the CSS framework for responsive UI design.
- **Font Awesome**: Supplies an icon library for UI elements.

## Python Libraries
- **Flask**: The web framework underpinning the dashboard and API.
- **Requests**: Used for HTTP client operations, particularly for Telegram API calls.
- **Threading**: Python's built-in threading for managing background processes.