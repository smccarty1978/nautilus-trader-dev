// Visualizer State
let state = {
    backtests: [],
    activeBacktest: "",
    trades: [],
    filteredTrades: [],
    selectedTradeIndex: -1,
    selectedTrade: null,
    resolution: "5s",
    padding: 15,
    filterType: "all",
    searchQuery: ""
};

// Chart References
let chart = null;
let series = {
    candles: null,
    shortEmaHigh: null,
    shortEmaLow: null,
    shortEmaClose: null,
    longEmaHigh: null,
    longEmaLow: null,
    regime: null,
    atr: null,
    hc: null,        // model risk-score line (Pane 2)
    hcState: null    // filter-decision ribbon (Pane 2)
};
// Pane-2 threshold guide lines (created once on the hc series)
let hcPriceLines = [];
// State codes emitted by studies/rank_filter_oos_validation/build_visualizer_indicators.py:
// 0 = SKIPPED (score >= frozen threshold, no exemption applied)
// 1 = EXEMPT-KEEP (score >= threshold but the R2/R4 exemption saved the trade)
// 3 = LOW-RISK-KEEP (score below threshold; kept without needing the exemption)
// (2 unused here; slot kept so other runs' state encodings still render sanely)
const HC_STATE_COLOR = { 3: '#26a69a', 2: '#cddc39', 1: '#ffa726', 0: '#ef5350' };
const HC_STATE_NAME = { 3: 'LOW-RISK KEEP', 2: 'SoftStall', 1: 'EXEMPT KEEP', 0: 'SKIPPED' };
let priceLines = {
    entry: null,
    exit: null
};
let markersApi = null;

// DOM Elements
const backtestSelect = document.getElementById("backtest-select");
const tradeSearch = document.getElementById("trade-search");
const filterBtns = document.querySelectorAll(".filter-btn");
const tradesList = document.getElementById("trades-list");
const tradeStats = document.getElementById("trade-stats");
const detailHeader = document.getElementById("detail-header");
const resolutionButtons = document.querySelectorAll("#resolution-buttons .btn");
const paddingSelect = document.getElementById("padding-select");
const prevTradeBtn = document.getElementById("prev-trade-btn");
const nextTradeBtn = document.getElementById("next-trade-btn");
const loadingOverlay = document.getElementById("loading-overlay");

// Show error in a red banner on screen
function showError(prefix, err) {
    const banner = document.getElementById("error-banner");
    const msgSpan = document.getElementById("error-message");
    if (banner && msgSpan) {
        banner.style.display = "block";
        msgSpan.textContent = `${prefix}: ${err.stack || err.message || err}`;
    }
}

// Initialize application
document.addEventListener("DOMContentLoaded", () => {
    console.log("DOM content loaded. Starting visualizer initialization...");
    
    try {
        initChart();
        console.log("Chart initialized successfully.");
    } catch (err) {
        console.error("Failed to initialize chart:", err);
        showError("Chart Init Error", err);
    }

    try {
        fetchBacktests();
        console.log("Requested backtests listing from API.");
    } catch (err) {
        console.error("Failed to trigger fetchBacktests:", err);
        showError("Fetch Backtests Error", err);
    }

    try {
        setupEventListeners();
        console.log("Event listeners configured.");
    } catch (err) {
        console.error("Failed to setup event listeners:", err);
        showError("Setup Listeners Error", err);
    }
});

// Create and configure Lightweight Chart
function initChart() {
    const container = document.getElementById("chart-container");
    container.innerHTML = ""; // Clear loader if any

    chart = LightweightCharts.createChart(container, {
        layout: {
            background: { type: 'solid', color: '#131722' },
            textColor: '#d1d4dc',
            fontSize: 12,
            fontFamily: 'Outfit, sans-serif',
        },
        grid: {
            vertLines: { color: '#2a2e39' },
            horzLines: { color: '#2a2e39' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: '#2a2e39',
        },
        timeScale: {
            borderColor: '#2a2e39',
            timeVisible: true,
            secondsVisible: true,
        },
    });

    // Regime Shading (Background)
    series.regimeShading = chart.addSeries(LightweightCharts.HistogramSeries, {
        priceScaleId: 'left',
        base: 0,
    });

    // Create Series
    series.candles = chart.addSeries(LightweightCharts.CandlestickSeries, {
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
    });

    // Initialize Markers API primitive for candles series
    markersApi = LightweightCharts.createSeriesMarkers(series.candles, []);

    // Short EMAs (Orange)
    series.shortEmaHigh = chart.addSeries(LightweightCharts.LineSeries, {
        color: 'rgba(255, 152, 0, 0.4)',
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        visible: false,
        lastValueVisible: false
    });
    series.shortEmaLow = chart.addSeries(LightweightCharts.LineSeries, {
        color: 'rgba(255, 152, 0, 0.4)',
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        visible: false,
        lastValueVisible: false
    });
    series.shortEmaClose = chart.addSeries(LightweightCharts.LineSeries, {
        color: '#ff9800',
        lineWidth: 2,
        lastValueVisible: false
    });

    // Long EMAs (Blue)
    series.longEmaHigh = chart.addSeries(LightweightCharts.LineSeries, {
        color: 'rgba(3, 169, 244, 0.5)',
        lineWidth: 1.5,
        lastValueVisible: false
    });
    series.longEmaLow = chart.addSeries(LightweightCharts.LineSeries, {
        color: 'rgba(3, 169, 244, 0.5)',
        lineWidth: 1.5,
        lastValueVisible: false
    });

    // ATR Series (in Pane 1)
    series.atr = chart.addSeries(LightweightCharts.LineSeries, {
        color: '#2962ff',
        lineWidth: 2,
        lastValueVisible: false
    }, 1); // Pane index 1

    // KNN Health state ribbon (Pane 2) — colored bars showing the regime-health
    // state in force at each 1m close (the value the exit logic actually saw).
    series.hcState = chart.addSeries(LightweightCharts.HistogramSeries, {
        priceScaleId: 'hc-ribbon',
        priceFormat: { type: 'volume' },
        lastValueVisible: false,
        base: 0
    }, 2);
    series.hcState.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    // KNN Health line hC = P(new_high3) - P(flip3)  (Pane 2)
    series.hc = chart.addSeries(LightweightCharts.LineSeries, {
        color: '#26c6da',
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        lastValueVisible: false,
        pointMarkersVisible: true   // 1m cadence — show points even on 1s/5s charts
    }, 2);
    // Threshold guide lines: frozen skip threshold (orange) + zero baseline.
    // NOTE: repurposed pane -- was KNN-health-specific (0.5/0.1/0.0); now a
    // generic 0-1 model-score view. Update FROZEN_SCORE_THRESHOLD per study.
    const FROZEN_SCORE_THRESHOLD = 0.12855426455573915;
    [[FROZEN_SCORE_THRESHOLD, '#ffa726'], [0.0, '#787b86']].forEach(([p, c]) => {
        hcPriceLines.push(series.hc.createPriceLine({
            price: p, color: c, lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true
        }));
    });

    // Configure pane relative heights
    const panes = chart.panes();
    if (panes && panes.length >= 3) {
        panes[0].setStretchFactor(5);   // Main pane
        panes[1].setStretchFactor(1);   // ATR pane
        panes[2].setStretchFactor(2);   // KNN health pane
    } else if (panes && panes.length >= 2) {
        panes[0].setStretchFactor(4);
        panes[1].setStretchFactor(1);
    }

    chart.priceScale('left').applyOptions({
        mode: LightweightCharts.PriceScaleMode.Normal,
        autoScale: true,
        scaleMargins: {
            top: 0, // Stretch across the entire chart background!
            bottom: 0,
        },
        borderVisible: false,
        visible: false, // Hide the left axis labels to keep it clean
    });

    // Legend Hover Tracking
    chart.subscribeCrosshairMove(param => {
        if (!param.time) {
            updateLegendValues(null);
            return;
        }

        const data = {};

        // Get OHLC
        const candleData = param.seriesData.get(series.candles);
        if (candleData) {
            data.ohlc = candleData;
        }

        // Get Indicators
        data.shortEmaClose = param.seriesData.get(series.shortEmaClose);
        data.shortEmaHigh = param.seriesData.get(series.shortEmaHigh);
        data.shortEmaLow = param.seriesData.get(series.shortEmaLow);
        data.longEmaHigh = param.seriesData.get(series.longEmaHigh);
        data.longEmaLow = param.seriesData.get(series.longEmaLow);
        
        const regimeData = param.seriesData.get(series.regimeShading);
        if (regimeData) {
            data.regimeValue = regimeData.regimeValue;
        }
        
        data.atr = param.seriesData.get(series.atr);
        data.hc = param.seriesData.get(series.hc);
        data.hcState = param.seriesData.get(series.hcState);

        updateLegendValues(data);
    });

    // Resize observer to handle flexbox container layout timing dynamically using parentElement to avoid infinite loop
    const parent = container.parentElement;
    const resizeObserver = new ResizeObserver(entries => {
        if (entries.length === 0) return;
        const width = parent.clientWidth;
        const height = parent.clientHeight;
        if (width > 0 && height > 0) {
            chart.resize(width, height);
            if (state.selectedTrade) {
                chart.priceScale('right').applyOptions({ autoScale: true });
                chart.timeScale().fitContent();
            }
        }
    });
    resizeObserver.observe(parent);
}

// Update the floating legend with hovered values
function updateLegendValues(data) {
    const ohlcEl = document.getElementById("legend-ohlc");
    const shortEl = document.getElementById("legend-short-ema");
    const longEl = document.getElementById("legend-long-ema");
    const regimeEl = document.getElementById("legend-regime");
    const atrEl = document.getElementById("legend-atr");
    const hcEl = document.getElementById("legend-hc");
    const hcStateEl = document.getElementById("legend-hc-state");

    if (!data || !data.ohlc) {
        ohlcEl.innerHTML = "-";
        shortEl.innerHTML = "-";
        longEl.innerHTML = "-";
        regimeEl.innerHTML = "-";
        if (atrEl) atrEl.innerHTML = "-";
        if (hcEl) hcEl.innerHTML = "-";
        if (hcStateEl) hcStateEl.innerHTML = "-";
        return;
    }

    const { open, high, low, close } = data.ohlc;
    const isUp = close >= open;
    const color = isUp ? '#26a69a' : '#ef5350';

    ohlcEl.innerHTML = `O <span style="color:${color}">${open.toFixed(2)}</span> ` +
                       `H <span style="color:${color}">${high.toFixed(2)}</span> ` +
                       `L <span style="color:${color}">${low.toFixed(2)}</span> ` +
                       `C <span style="color:${color}">${close.toFixed(2)}</span>`;

    if (data.shortEmaClose) {
        shortEl.innerHTML = `C: <span style="color:#ff9800">${data.shortEmaClose.value.toFixed(2)}</span>`;
    } else {
        shortEl.innerHTML = "-";
    }

    if (data.longEmaHigh && data.longEmaLow) {
        longEl.innerHTML = `H: <span style="color:#03a9f4">${data.longEmaHigh.value.toFixed(2)}</span> ` +
                           `L: <span style="color:#03a9f4">${data.longEmaLow.value.toFixed(2)}</span>`;
    } else {
        longEl.innerHTML = "-";
    }

    if (data && data.regimeValue !== undefined) {
        const rVal = data.regimeValue;
        const rColor = rVal === 1 ? '#089981' : (rVal === -1 ? '#f23645' : '#787b86');
        const rText = rVal === 1 ? 'BULLISH (+1)' : (rVal === -1 ? 'BEARISH (-1)' : 'NEUTRAL (0)');
        regimeEl.innerHTML = `<span style="color:${rColor}; font-weight: 600;">${rText}</span>`;
    } else {
        regimeEl.innerHTML = "-";
    }

    if (atrEl) {
        if (data.atr) {
            atrEl.innerHTML = `Val: <span style="color:#2962ff">${data.atr.value.toFixed(2)}</span>`;
        } else {
            atrEl.innerHTML = "-";
        }
    }

    if (hcEl) {
        hcEl.innerHTML = data.hc
            ? `<span style="color:#26c6da">${data.hc.value.toFixed(3)}</span>`
            : "-";
    }
    if (hcStateEl) {
        if (data.hcState && data.hcState.value !== undefined) {
            const code = Math.round(data.hcState.value) - 1;  // bar height = code+1
            const col = HC_STATE_COLOR[code] || '#787b86';
            hcStateEl.innerHTML = `<span style="color:${col}; font-weight:600">${HC_STATE_NAME[code] || '-'}</span>`;
        } else {
            hcStateEl.innerHTML = "-";
        }
    }
}

// Fetch list of backtest runs from API
async function fetchBacktests() {
    try {
        const response = await fetch("/api/backtests");
        const data = await response.json();
        state.backtests = data.backtests || [];
        
        backtestSelect.innerHTML = `<option value="">-- Select Backtest --</option>`;
        state.backtests.forEach(bt => {
            const option = document.createElement("option");
            option.value = bt.id;
            option.textContent = bt.name;
            backtestSelect.appendChild(option);
        });
    } catch (err) {
        console.error("Failed to fetch backtests:", err);
    }
}

// Fetch list of trades for the active backtest
async function fetchTrades(backtestId) {
    if (!backtestId) {
        state.trades = [];
        filterAndRenderTrades();
        return;
    }

    showLoading(true);
    try {
        const response = await fetch(`/api/backtests/${backtestId}/trades`);
        const data = await response.json();
        state.trades = data.trades || [];
        filterAndRenderTrades();
    } catch (err) {
        console.error("Failed to fetch trades:", err);
    } finally {
        showLoading(false);
    }
}

// Filter and render the sidebar trades
function filterAndRenderTrades() {
    const query = state.searchQuery.toLowerCase();
    
    state.filteredTrades = state.trades.filter(t => {
        // Filter by win/loss status
        const isWin = t.pnl > 0;
        if (state.filterType === "wins" && !isWin) return false;
        if (state.filterType === "losses" && isWin) return false;

        // Filter by search query
        if (query) {
            const idMatch = t.id.toString().includes(query);
            const reasonMatch = t.exit_reason.toLowerCase().includes(query);
            const dateMatch = t.entry_time.toLowerCase().includes(query);
            return idMatch || reasonMatch || dateMatch;
        }
        return true;
    });

    // Render list
    tradesList.innerHTML = "";
    state.filteredTrades.forEach((t, idx) => {
        const li = document.createElement("li");
        li.className = `trade-item ${idx === state.selectedTradeIndex ? 'selected' : ''}`;
        li.dataset.index = idx;

        const isWin = t.pnl > 0;
        const pnlSign = t.pnl >= 0 ? "+" : "";
        const dirClass = t.direction.toLowerCase();
        
        li.innerHTML = `
            <div class="trade-item-row">
                <span class="trade-id">#${t.id}</span>
                <span class="trade-direction ${dirClass}">${t.direction}</span>
                <span class="trade-pnl ${isWin ? 'pnl-win' : 'pnl-loss'}">${pnlSign}${t.pnl.toFixed(2)}</span>
            </div>
            <div class="trade-item-row">
                <span class="trade-time">${formatShortDate(t.entry_time)}</span>
                <span class="trade-reason-pill">${t.exit_reason}</span>
            </div>
        `;
        li.addEventListener("click", () => selectTrade(idx));
        tradesList.appendChild(li);
    });

    // Update Stats
    const total = state.trades.length;
    const wins = state.trades.filter(t => t.pnl > 0).length;
    const winRate = total > 0 ? (wins / total) * 100 : 0;
    tradeStats.textContent = `Trades: ${total} | Win Rate: ${winRate.toFixed(1)}% (Filtered: ${state.filteredTrades.length})`;

    // Reset selected index if out of bounds
    if (state.selectedTradeIndex >= state.filteredTrades.length) {
        state.selectedTradeIndex = state.filteredTrades.length > 0 ? 0 : -1;
    }
}

// Select trade and trigger chart load
async function selectTrade(filteredIndex) {
    if (filteredIndex < 0 || filteredIndex >= state.filteredTrades.length) return;

    state.selectedTradeIndex = filteredIndex;
    state.selectedTrade = state.filteredTrades[filteredIndex];

    // Highlight active item
    const items = tradesList.querySelectorAll(".trade-item");
    items.forEach(el => el.classList.remove("selected"));
    if (items[filteredIndex]) {
        items[filteredIndex].classList.add("selected");
        items[filteredIndex].scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    // Update Detail Header
    document.querySelector(".trade-summary-stub").style.display = "none";
    document.querySelector(".trade-details-container").style.display = "flex";

    renderTradeDetails(state.selectedTrade);

    // Update Navigation buttons
    prevTradeBtn.disabled = filteredIndex === 0;
    nextTradeBtn.disabled = filteredIndex === state.filteredTrades.length - 1;

    // Load Candles
    await loadChartData();
}

// Render selected trade details in the header
function renderTradeDetails(trade) {
    document.getElementById("val-trade-id").textContent = `#${trade.id}`;
    document.getElementById("val-direction").textContent = trade.direction;
    document.getElementById("val-direction").className = `detail-value ${trade.direction.toLowerCase() === 'long' ? 'win' : 'loss'}`;
    document.getElementById("val-entry-px").textContent = trade.entry_price.toFixed(2);
    document.getElementById("val-exit-px").textContent = trade.exit_price ? trade.exit_price.toFixed(2) : "N/A";
    document.getElementById("val-reason").textContent = trade.exit_reason;
    document.getElementById("val-entry-time").textContent = formatFullDate(trade.entry_time);

    const pnlVal = trade.pnl;
    const pnlEl = document.getElementById("val-pnl");
    pnlEl.textContent = `${pnlVal >= 0 ? "+" : ""}${pnlVal.toFixed(2)} pts (${trade.pnl_atr.toFixed(2)} ATR)`;
    pnlEl.className = `detail-value ${pnlVal >= 0 ? 'win' : 'loss'}`;
}

// Update specific sidebar list item after dynamic reconstruction
function updateSidebarItem(filteredIndex, trade) {
    const items = tradesList.children;
    if (filteredIndex >= 0 && filteredIndex < items.length) {
        const li = items[filteredIndex];
        const isWin = trade.pnl > 0;
        const pnlSign = trade.pnl >= 0 ? "+" : "";
        const dirClass = trade.direction.toLowerCase();
        
        li.innerHTML = `
            <div class="trade-item-row">
                <span class="trade-id">#${trade.id}</span>
                <span class="trade-direction ${dirClass}">${trade.direction}</span>
                <span class="trade-pnl ${isWin ? 'pnl-win' : 'pnl-loss'}">${pnlSign}${trade.pnl.toFixed(2)}</span>
            </div>
            <div class="trade-item-row">
                <span class="trade-time">${formatShortDate(trade.entry_time)}</span>
                <span class="trade-reason-pill">${trade.exit_reason}</span>
            </div>
        `;
    }
}

// Load Candles & Indicators for selected trade
async function loadChartData() {
    if (!state.selectedTrade) return;

    showLoading(true);
    
    // Force chart resize to match parent container client bounds before loading data
    const container = document.getElementById("chart-container");
    const parent = container.parentElement;
    const width = parent.clientWidth;
    const height = parent.clientHeight;
    if (width > 0 && height > 0) {
        chart.resize(width, height);
    }

    try {
        const tradeId = state.selectedTrade.id;
        const res = await fetch(`/api/backtests/${state.activeBacktest}/trades/${tradeId}/candles?resolution=${state.resolution}&padding=${state.padding}`);
        const data = await res.json();

        if (data.error) {
            console.error("Server error loading trade:", data.error);
            return;
        }

        if (data.trade) {
            // Update cache and state with reconstructed details
            state.selectedTrade = data.trade;
            state.filteredTrades[state.selectedTradeIndex] = data.trade;
            
            // Re-render UI elements
            renderTradeDetails(data.trade);
            updateSidebarItem(state.selectedTradeIndex, data.trade);
        }

        const candles = data.candles || [];
        const indicators = data.indicators || {};
        const exitPrice = state.selectedTrade.exit_price;

        // Set series data
        series.candles.setData(candles.map(c => ({
            time: c.time,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close
        })));

        // Set EMA Indicators
        if (indicators.short_ema_close) {
            series.shortEmaClose.setData(indicators.short_ema_close);
            series.shortEmaHigh.setData(indicators.short_ema_high || []);
            series.shortEmaLow.setData(indicators.short_ema_low || []);
        } else {
            series.shortEmaClose.setData([]);
            series.shortEmaHigh.setData([]);
            series.shortEmaLow.setData([]);
        }

        if (indicators.long_ema_high) {
            series.longEmaHigh.setData(indicators.long_ema_high);
            series.longEmaLow.setData(indicators.long_ema_low);
        } else {
            series.longEmaHigh.setData([]);
            series.longEmaLow.setData([]);
        }

        // Set ATR Indicator
        if (indicators.atr) {
            series.atr.setData(indicators.atr);
        } else {
            series.atr.setData([]);
        }

        // Set KNN Health (Pane 2): hC line + state ribbon (bar height=code+1, colored by state)
        const knn = data.knn || {};
        series.hc.setData(knn.hc || []);
        const ribbon = (knn.hc_state || []).map(p => {
            const code = Math.round(p.value);
            return { time: p.time, value: code + 1, color: HC_STATE_COLOR[code] || '#787b86' };
        });
        series.hcState.setData(ribbon);

        // Set Regime Shading (Background)
        if (indicators.regime) {
            series.regimeShading.setData(indicators.regime.map(r => ({
                time: r.time,
                value: 1,
                color: r.value === 1 ? 'rgba(38, 166, 154, 0.08)' : (r.value === -1 ? 'rgba(239, 83, 80, 0.08)' : 'rgba(0, 0, 0, 0)'),
                regimeValue: r.value
            })));
        } else {
            series.regimeShading.setData([]);
        }

        // Set Trade Markers (Arrows)
        const markers = [];
        const entryTime = Math.floor(new Date(state.selectedTrade.entry_time).getTime() / 1000);
        
        // Find closest candle matching entry time
        const entryCandle = findClosestCandle(candles, entryTime);
        if (entryCandle) {
            markers.push({
                time: entryCandle.time,
                position: state.selectedTrade.direction.toLowerCase() === 'long' ? 'belowBar' : 'aboveBar',
                color: '#089981',
                shape: 'arrowUp',
                text: 'ENTRY',
                size: 2
            });
        }

        if (state.selectedTrade.exit_time) {
            const exitTime = Math.floor(new Date(state.selectedTrade.exit_time).getTime() / 1000);
            const exitCandle = findClosestCandle(candles, exitTime);
            if (exitCandle) {
                markers.push({
                    time: exitCandle.time,
                    position: state.selectedTrade.direction.toLowerCase() === 'long' ? 'aboveBar' : 'belowBar',
                    color: '#f23645',
                    shape: 'arrowDown',
                    text: `EXIT (${state.selectedTrade.exit_reason})`,
                    size: 2
                });
            }
        }
        
        markersApi.setMarkers(markers);

        // Update Price Lines (Horizontal)
        // Clear old price lines
        if (priceLines.entry) series.candles.removePriceLine(priceLines.entry);
        if (priceLines.exit) series.candles.removePriceLine(priceLines.exit);

        priceLines.entry = series.candles.createPriceLine({
            price: state.selectedTrade.entry_price,
            color: '#2962ff',
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Solid,
            axisLabelVisible: true,
            title: `Entry Price (${state.selectedTrade.entry_price.toFixed(2)})`,
        });

        if (state.selectedTrade.exit_price) {
            const exitReasonStr = state.selectedTrade.exit_reason ? ` (${state.selectedTrade.exit_reason})` : '';
            priceLines.exit = series.candles.createPriceLine({
                price: state.selectedTrade.exit_price,
                color: '#ef5350',
                lineWidth: 2,
                lineStyle: LightweightCharts.LineStyle.Solid,
                axisLabelVisible: true,
                title: `Exit Price${exitReasonStr} (${state.selectedTrade.exit_price.toFixed(2)})`,
            });
        }

        // Fit time scale to show the entire trade window beautifully and reset autoScale after rendering updates
        logChartDiagnostics("loadChartData Pre-Timeout", candles);
        const fitChart = () => {
            chart.priceScale('right').applyOptions({ autoScale: true });
            chart.timeScale().fitContent();
        };
        fitChart();
        setTimeout(fitChart, 50);
        setTimeout(fitChart, 200);
        requestAnimationFrame(() => {
            fitChart();
            logChartDiagnostics("loadChartData Post-Timeout", candles);
        });

    } catch (err) {
        console.error("Failed to load chart data:", err);
        showError("Chart Load Error", err);
    } finally {
        showLoading(false);
    }
}

// Find closest candle index for a given timestamp (in seconds)
function findClosestCandle(candles, timestampSec) {
    if (!candles || candles.length === 0) return null;
    
    let closest = candles[0];
    let minDiff = Math.abs(closest.time - timestampSec);

    for (let i = 1; i < candles.length; i++) {
        let diff = Math.abs(candles[i].time - timestampSec);
        if (diff < minDiff) {
            minDiff = diff;
            closest = candles[i];
        }
    }
    return closest;
}

// Setup Dashboard Interactions & Buttons
function setupEventListeners() {
    // Backtest selector change
    backtestSelect.addEventListener("change", (e) => {
        state.activeBacktest = e.target.value;
        state.selectedTradeIndex = -1;
        state.selectedTrade = null;
        fetchTrades(state.activeBacktest);
    });

    // Search bar
    tradeSearch.addEventListener("input", (e) => {
        state.searchQuery = e.target.value;
        filterAndRenderTrades();
    });

    // Filter Buttons
    filterBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            filterBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            state.filterType = btn.dataset.filter;
            filterAndRenderTrades();
        });
    });

    // Resolution Toggles
    resolutionButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            resolutionButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            state.resolution = btn.dataset.res;
            loadChartData();
        });
    });

    // Padding dropdown
    paddingSelect.addEventListener("change", (e) => {
        state.padding = parseInt(e.target.value);
        loadChartData();
    });

    // Navigation buttons
    prevTradeBtn.addEventListener("click", () => {
        if (state.selectedTradeIndex > 0) {
            selectTrade(state.selectedTradeIndex - 1);
        }
    });

    nextTradeBtn.addEventListener("click", () => {
        if (state.selectedTradeIndex < state.filteredTrades.length - 1) {
            selectTrade(state.selectedTradeIndex + 1);
        }
    });

    // Auto scale / fit button
    const autoScaleBtn = document.getElementById("auto-scale-btn");
    if (autoScaleBtn) {
        autoScaleBtn.addEventListener("click", () => {
            chart.priceScale('right').applyOptions({ autoScale: true });
            chart.timeScale().fitContent();
            logChartDiagnostics("Auto Fit Button Clicked", null);
        });
    }

    // Stop Server button
    const stopServerBtn = document.getElementById("stop-server-btn");
    if (stopServerBtn) {
        stopServerBtn.addEventListener("click", async () => {
            if (confirm("Are you sure you want to shut down the Python visualizer server?")) {
                const shutdownScreen = document.getElementById("shutdown-screen");
                if (shutdownScreen) {
                    shutdownScreen.style.display = "flex";
                }
                try {
                    await fetch("/api/shutdown", { method: "POST" });
                } catch (err) {
                    console.log("Server shut down as expected:", err);
                }
            }
        });
    }

    // Keyboard Navigation
    window.addEventListener("keydown", (e) => {
        // Prevent scroll if arrow keys pressed
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
            // Check if search bar is focused
            if (document.activeElement === tradeSearch) return;
            
            e.preventDefault();
            if (e.key === "ArrowLeft" && state.selectedTradeIndex > 0) {
                selectTrade(state.selectedTradeIndex - 1);
            } else if (e.key === "ArrowRight" && state.selectedTradeIndex < state.filteredTrades.length - 1) {
                selectTrade(state.selectedTradeIndex + 1);
            }
        } else if (e.key.toLowerCase() === "a") {
            // Check if search bar is focused or typing in input
            if (document.activeElement === tradeSearch || document.activeElement.tagName === "INPUT") return;
            
            e.preventDefault();
            chart.priceScale('right').applyOptions({ autoScale: true });
            chart.timeScale().fitContent();
            logChartDiagnostics("Auto Fit Keypress", null);
        }
    });
}

// Helpers
function showLoading(show) {
    loadingOverlay.style.display = show ? "flex" : "none";
}

function formatShortDate(dateStr) {
    if (!dateStr) return "-";
    const d = new Date(dateStr);
    return `${d.getMonth() + 1}/${d.getDate()} ${d.toTimeString().split(' ')[0]}`;
}

function formatFullDate(dateStr) {
    if (!dateStr) return "-";
    const d = new Date(dateStr);
    return d.toISOString().replace('T', ' ').substring(0, 19);
}

function logChartDiagnostics(stage, candlesArray) {
    try {
        const container = document.getElementById("chart-container");
        const rightScale = chart.priceScale('right');
        const rightScaleOpts = rightScale ? rightScale.options() : null;
        
        let candleInfo = "No candles data";
        if (candlesArray && candlesArray.length > 0) {
            const minTime = candlesArray[0].time;
            const maxTime = candlesArray[candlesArray.length - 1].time;
            const lows = candlesArray.map(c => c.low);
            const highs = candlesArray.map(c => c.high);
            const minLow = Math.min(...lows);
            const maxHigh = Math.max(...highs);
            candleInfo = `Candles: ${candlesArray.length}, Time range: ${minTime} to ${maxTime}, Price range: ${minLow.toFixed(2)} to ${maxHigh.toFixed(2)}`;
        }
        
        const visibleRange = chart.timeScale().getVisibleRange();
        const visibleRangeStr = visibleRange ? `${visibleRange.from} to ${visibleRange.to}` : "null";
        
        const parent = container.parentElement;
        const msg = `[DIAGNOSTICS - ${stage}] Container: ${container.clientWidth}x${container.clientHeight}, Parent: ${parent.clientWidth}x${parent.clientHeight}, ` +
                    `${candleInfo}, TimeScale Visible: ${visibleRangeStr}, ` +
                    `rightPriceScale autoScale: ${rightScaleOpts ? rightScaleOpts.autoScale : 'unknown'}`;
        console.log(msg);
        sendErrorToBackend(msg);
    } catch (e) {
        console.error("Failed to log diagnostics:", e);
        sendErrorToBackend(`DIAGNOSTICS ERROR: ${e.message}`);
    }
}
