class TradingDashboard {
    constructor() {
        this.lastUpdateTime = null;
        this.isUpdating = false;
        
        this.bindEvents();
        this.startDataUpdates();
        
        // Initial load
        this.updateDashboard();
    }

    bindEvents() {
        // Bot control buttons (NO password check implemented here)
        document.getElementById('start-bot').addEventListener('click', () => {
            this.startBot();
        });

        document.getElementById('stop-bot').addEventListener('click', () => {
            this.stopBot();
        });

        document.getElementById('close-position').addEventListener('click', () => {
            this.closePosition();
        });

        document.getElementById('delete-trade').addEventListener('click', () => {
            this.deleteLastTrade();
        });

        document.getElementById('reset-balance').addEventListener('click', () => {
            this.resetBalance();
        });
    }

    // *** ФУНКЦИЯ withPasswordCheck БЫЛА УДАЛЕНА ***

    async startBot() {
        try {
            const response = await fetch('/api/start_bot', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            
            if (response.ok) {
                this.showNotification('success', data.message || 'Bot started successfully');
            } else {
                this.showNotification('error', data.error || 'Failed to start bot');
            }
        } catch (error) {
            this.showNotification('error', 'Server connection error');
            console.error('Start bot error:', error);
        }
    }

    async stopBot() {
        try {
            const response = await fetch('/api/stop_bot', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            
            if (response.ok) {
                this.showNotification('success', data.message || 'Bot stopped successfully');
            } else {
                this.showNotification('error', data.error || 'Failed to stop bot');
            }
        } catch (error) {
            this.showNotification('error', 'Server connection error');
            console.error('Stop bot error:', error);
        }
    }

    async closePosition() {
        try {
            const response = await fetch('/api/close_position', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            
            if (response.ok) {
                this.showNotification('success', data.message || 'Position closed successfully');
            } else {
                this.showNotification('error', data.error || 'Failed to close position');
            }
        } catch (error) {
            this.showNotification('error', 'Server connection error');
            console.error('Close position error:', error);
        }
    }

    async deleteLastTrade() {
        try {
            const response = await fetch('/api/delete_last_trade', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            
            if (response.ok) {
                this.showNotification('success', data.message || 'Last trade deleted successfully');
                this.updateDashboard();
            } else {
                this.showNotification('error', data.error || 'Failed to delete last trade');
            }
        } catch (error) {
            this.showNotification('error', 'Server connection error');
            console.error('Delete trade error:', error);
        }
    }

    async resetBalance() {
        try {
            const response = await fetch('/api/reset_balance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            
            if (response.ok) {
                this.showNotification('success', data.message || 'Balance reset successfully');
                this.updateDashboard();
            } else {
                this.showNotification('error', data.error || 'Failed to reset balance');
            }
        } catch (error) {
            this.showNotification('error', 'Server connection error');
            console.error('Reset balance error:', error);
        }
    }

    async updateDashboard() {
        if (this.isUpdating) {
            return;
        }

        this.isUpdating = true;

        try {
            const response = await fetch('/api/status');
            if (!response.ok) {
                console.error('Status fetch failed');
                return;
            }

            const data = await response.json();

            // Update bot status
            const statusBadge = document.getElementById('bot-status');
            if (data.bot_running) {
                statusBadge.textContent = 'RUNNING';
                statusBadge.className = 'badge bg-success';
            } else {
                statusBadge.textContent = 'STOPPED';
                statusBadge.className = 'badge bg-danger';
            }

            // Update balance
            document.getElementById('balance').textContent = `$${parseFloat(data.balance).toFixed(2)}`;
            document.getElementById('available').textContent = `$${parseFloat(data.available).toFixed(2)}`;

            // Update current price
            if (data.current_price) {
                document.getElementById('current-price').textContent = `$${parseFloat(data.current_price).toFixed(2)}`;
            }

            // Update SAR directions
            if (data.sar_directions) {
                this.updateSARDirections(data.sar_directions);
            }

            // Update position status
            if (data.in_position && data.position) {
                document.getElementById('position-status').textContent = data.position.side.toUpperCase();
                this.updatePosition(data.position, data.current_price);
            } else {
                document.getElementById('position-status').textContent = 'No Position';
                this.clearPosition();
            }

            // Update trades
            if (data.trades) {
                this.updateTrades(data.trades);
            }

            this.lastUpdateTime = new Date();
        } catch (error) {
            console.error('Dashboard update error:', error);
        } finally {
            this.isUpdating = false;
        }
    }

    updateSARDirections(directions) {
        console.log('updateSARDirections called with:', directions);
        
        const timeframes = ['1m', '5m', '15m'];
        let allMatch = true;
        let matchDirection = null;
        
        timeframes.forEach(tf => {
            const element = document.getElementById(`sar-${tf}`);
            const container = document.getElementById(`sar-${tf}-container`);
            const direction = directions[tf];
            
            console.log(`Processing ${tf}: element=${element}, container=${container}, direction=${direction}`);
            
            if (element && container) {
                element.className = 'badge sar-badge';
                
                if (direction === 'long') {
                    element.textContent = 'LONG';
                    element.classList.add('bg-success');
                    container.classList.remove('text-danger');
                    container.classList.add('text-success');
                    if (matchDirection === null) {
                        matchDirection = 'long';
                    } else if (matchDirection !== 'long') {
                        allMatch = false;
                    }
                } else if (direction === 'short') {
                    element.textContent = 'SHORT';
                    element.classList.add('bg-danger');
                    container.classList.remove('text-success');
                    container.classList.add('text-danger');
                    if (matchDirection === null) {
                        matchDirection = 'short';
                    } else if (matchDirection !== 'short') {
                        allMatch = false;
                    }
                } else {
                    element.textContent = 'N/A';
                    element.classList.add('bg-secondary');
                    container.classList.remove('text-success', 'text-danger');
                    allMatch = false;
                }
            }
        });
        
        // Update signal status
        const signalElement = document.getElementById('signal-status');
        if (signalElement) {
            if (allMatch && matchDirection) {
                if (matchDirection === 'long') {
                    signalElement.textContent = 'LONG SIGNAL';
                    signalElement.className = 'badge bg-success signal-badge';
                } else {
                    signalElement.textContent = 'SHORT SIGNAL';
                    signalElement.className = 'badge bg-danger signal-badge';
                }
            } else {
                signalElement.textContent = 'NO SIGNAL';
                signalElement.className = 'badge bg-secondary signal-badge';
            }
        }
    }

    updatePosition(position, currentPrice) {
        const noPosition = document.getElementById('no-position');
        const currentPosition = document.getElementById('current-position');
        
        if (noPosition) noPosition.classList.add('d-none');
        if (currentPosition) currentPosition.classList.remove('d-none');
        
        // Side
        const sideBadge = document.getElementById('pos-side');
        if (sideBadge) {
            sideBadge.textContent = position.side.toUpperCase();
            sideBadge.className = position.side === 'long' ? 'badge bg-success' : 'badge bg-danger';
        }
        
        // Color class for all position elements
        const colorClass = position.side === 'long' ? 'text-success' : 'text-danger';
        
        // Entry price
        const entryElement = document.getElementById('pos-entry');
        if (entryElement) {
            entryElement.textContent = `$${parseFloat(position.entry_price).toFixed(2)}`;
            entryElement.className = colorClass;
        }
        
        // Size
        const sizeElement = document.getElementById('pos-size');
        if (sizeElement) {
            sizeElement.textContent = `${parseFloat(position.size_base).toFixed(6)} ETH`;
            sizeElement.className = colorClass;
        }
        
        // Notional value
        const notionalElement = document.getElementById('pos-notional');
        if (notionalElement) {
            notionalElement.textContent = `$${parseFloat(position.notional).toFixed(2)}`;
            notionalElement.className = colorClass;
        }
        
        // Entry time
        const timeElement = document.getElementById('pos-time');
        if (timeElement && position.entry_time) {
            const entryTime = new Date(position.entry_time);
            timeElement.textContent = entryTime.toLocaleTimeString();
            timeElement.className = colorClass;
        }
        
        // P&L
        const pnlElement = document.getElementById('pos-pnl');
        if (pnlElement && currentPrice) {
            const entryPrice = parseFloat(position.entry_price);
            const size = parseFloat(position.size_base);
            let pnl;
            
            if (position.side === 'long') {
                pnl = (currentPrice - entryPrice) * size;
            } else {
                pnl = (entryPrice - currentPrice) * size;
            }
            
            pnlElement.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} USDT`;
            pnlElement.className = pnl >= 0 ? 'text-success' : 'text-danger'; // Use actual P&L color logic
        }
    }

    clearPosition() {
        const noPosition = document.getElementById('no-position');
        const currentPosition = document.getElementById('current-position');
        
        if (noPosition) noPosition.classList.remove('d-none');
        if (currentPosition) currentPosition.classList.add('d-none');
    }

    updateTrades(trades) {
        const container = document.getElementById('trades-container');
        if (!container) return;
        
        if (!trades || trades.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-4">
                    <i class="fas fa-clock fa-2x mb-3"></i>
                    <p>No completed trades</p>
                </div>
            `;
            return;
        }
        
        // Show last 50 trades
        const recentTrades = trades.slice(-50).reverse();
        
        const tradesHtml = recentTrades.map(trade => {
            const pnl = parseFloat(trade.pnl);
            const pnlClass = pnl >= 0 ? 'text-success' : 'text-danger';
            const sideClass = trade.side === 'long' ? 'bg-success' : 'bg-danger';
            
            const exitTime = trade.exit_time || trade.time;
            const exitDate = exitTime ? new Date(exitTime).toLocaleString() : 'N/A';
            
            return `
                <div class="list-group-item bg-dark border-secondary mb-3">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <span class="badge ${sideClass}">${trade.side.toUpperCase()}</span>
                            <span class="${pnlClass} fw-bold ms-2">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</span>
                        </div>
                        <small class="text-muted">
                            ${exitDate}
                        </small>
                    </div>
                    <div class="mt-2">
                        <small class="text-muted">
                            Entry: $${trade.entry_price.toFixed(2)} → Exit: $${trade.exit_price.toFixed(2)}
                        </small>
                    </div>
                </div>
            `;
        }).join('');
        
        container.innerHTML = tradesHtml;
    }

    showNotification(type, message) {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'error' ? 'danger' : 'success'} alert-dismissible fade show position-fixed`;
        notification.style.top = '20px';
        notification.style.right = '20px';
        notification.style.zIndex = '9999';
        notification.style.minWidth = '300px';
        
        notification.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(notification);
        
        // Auto remove after 5 seconds
        setTimeout(() => {
            notification.remove();
        }, 5000);
    }

    startDataUpdates() {
        // Update dashboard every 3 seconds
        setInterval(() => {
            this.updateDashboard();
        }, 3000);
    }
}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new TradingDashboard();
});
