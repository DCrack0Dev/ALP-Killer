package com.alpacatalk.trading.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.alpacatalk.trading.TradingViewModel
import com.alpacatalk.trading.data.AutomationStatusResponse
import com.alpacatalk.trading.data.ConnectionState
import com.alpacatalk.trading.data.TradingUiState
import com.alpacatalk.trading.data.VerifiedEnvironment
import kotlinx.coroutines.launch

private enum class Destination(val route: String, val title: String) {
    DASHBOARD("dashboard", "Dashboard"),
    ACCOUNT("account", "Account"),
    POSITIONS("positions", "Positions"),
    ORDERS("orders", "Orders & fills"),
    SIGNALS("signals", "Signals"),
    BACKTEST("backtest", "Backtest"),
    RISK("risk", "Risk"),
    AUTOMATION("automation", "Automation"),
    AUDIT("audit", "Audit log"),
    HEALTH("health", "System health"),
    SETTINGS("settings", "Settings"),
    EMERGENCY("emergency", "Emergency stop"),
}

@Composable
fun AlpacaTradingApp(viewModel: TradingViewModel) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    if (state.connectionState == ConnectionState.CONNECTED) {
        TradingNavigation(state, viewModel)
    } else {
        SecureConnectionWizard(state, viewModel)
    }
}

@Composable
private fun SecureConnectionWizard(state: TradingUiState, viewModel: TradingViewModel) {
    var backendUrl by remember { mutableStateOf("https://") }
    var passphrase by remember { mutableStateOf("") }
    var apiKey by remember { mutableStateOf("") }
    var apiSecret by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Spacer(Modifier.height(32.dp))
            Text("Alpaca Trading Assistant", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text(
                "A single-user remote control for a secure backend. This Android client never submits broker orders.",
                style = MaterialTheme.typography.bodyLarge,
            )
            SafetyDisclosure()
            if (state.backendOffline) OfflineBanner()
            ErrorOrInfo(state)

            when (state.connectionState) {
                ConnectionState.DISCONNECTED -> {
                    Text("1. Connect to your backend", style = MaterialTheme.typography.titleLarge)
                    Text("Use HTTPS. Debug builds accept HTTP only for localhost development.")
                    OutlinedTextField(
                        value = backendUrl,
                        onValueChange = { backendUrl = it },
                        label = { Text("Backend URL") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = passphrase,
                        onValueChange = { passphrase = it },
                        label = { Text("Backend passphrase") },
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Button(
                        onClick = {
                            scope.launch {
                                viewModel.establishBackendSession(backendUrl, passphrase)
                                // The passphrase has no persistence path and is released after the response.
                                passphrase = ""
                            }
                        },
                        enabled = backendUrl.isNotBlank() && passphrase.isNotBlank() && !state.isLoading,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        if (state.isLoading) LoadingLabel("Connecting") else Text("Create secure session")
                    }
                }

                ConnectionState.SESSION_READY, ConnectionState.VALIDATING -> {
                    Text("2. Validate Alpaca credentials", style = MaterialTheme.typography.titleLarge)
                    Text(
                        "Credentials are masked, sent once to the backend validator, then cleared. " +
                            "Auto-detection is server-side; this screen never chooses paper or live.",
                    )
                    OutlinedTextField(
                        value = apiKey,
                        onValueChange = { apiKey = it },
                        label = { Text("Alpaca API key") },
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = apiSecret,
                        onValueChange = { apiSecret = it },
                        label = { Text("Alpaca API secret") },
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Button(
                        onClick = {
                            scope.launch {
                                viewModel.validateBrokerCredentials(apiKey.toCharArray(), apiSecret.toCharArray())
                                // ViewModel clears CharArrays after the response; clear Compose memory too.
                                apiKey = ""
                                apiSecret = ""
                            }
                        },
                        enabled = apiKey.isNotBlank() && apiSecret.isNotBlank() && !state.isLoading,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        if (state.isLoading) LoadingLabel("Validating") else Text("Validate securely")
                    }
                    Text(
                        "Connecting live credentials never enables automation. Separate server-side risk controls and explicit activation are required.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }

                else -> Unit
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TradingNavigation(state: TradingUiState, viewModel: TradingViewModel) {
    val navController = rememberNavController()
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val entry by navController.currentBackStackEntryAsState()
    val currentRoute = entry?.destination?.route ?: Destination.DASHBOARD.route
    var emergencyConfirmationOpen by remember { mutableStateOf(false) }
    val currentTitle = Destination.entries.firstOrNull { it.route == currentRoute }?.title ?: "Trading assistant"

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet {
                Text(
                    "Trading assistant",
                    style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.padding(20.dp),
                )
                VerifiedEnvironmentBanner(state.environment)
                Spacer(Modifier.height(8.dp))
                Destination.entries.forEach { destination ->
                    Text(
                        text = destination.title,
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = if (destination.route == currentRoute) FontWeight.Bold else FontWeight.Normal,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable {
                                navController.navigate(destination.route) {
                                    popUpTo(Destination.DASHBOARD.route) { saveState = true }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                                scope.launch { drawerState.close() }
                            }
                            .padding(horizontal = 24.dp, vertical = 14.dp),
                    )
                }
            }
        },
    ) {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text(currentTitle) },
                    navigationIcon = {
                        TextButton(onClick = { scope.launch { drawerState.open() } }) {
                            Text("Menu")
                        }
                    },
                    actions = {
                        TextButton(onClick = viewModel::refresh, enabled = !state.isLoading) { Text("Refresh") }
                    },
                )
            },
            floatingActionButton = {
                ExtendedFloatingActionButton(
                    onClick = { emergencyConfirmationOpen = true },
                    containerColor = LiveRed,
                    contentColor = Color.White,
                    icon = { Text("!") },
                    text = { Text("Emergency stop") },
                )
            },
        ) { padding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
            ) {
                // This is intentionally outside individual destinations so it persists on every screen.
                VerifiedEnvironmentBanner(state.environment)
                if (state.backendOffline) OfflineBanner()
                ErrorOrInfo(state)
                AppNavHost(navController, state, viewModel, Modifier.weight(1f)) {
                    emergencyConfirmationOpen = true
                }
            }
        }
    }

    if (emergencyConfirmationOpen) {
        EmergencyConfirmation(
            inProgress = state.isActionInProgress,
            onConfirm = {
                emergencyConfirmationOpen = false
                viewModel.activateKillSwitch()
            },
            onDismiss = { emergencyConfirmationOpen = false },
        )
    }
}

@Composable
private fun AppNavHost(
    navController: NavHostController,
    state: TradingUiState,
    viewModel: TradingViewModel,
    modifier: Modifier,
    requestEmergencyConfirmation: () -> Unit,
) {
    NavHost(navController, startDestination = Destination.DASHBOARD.route, modifier = modifier) {
        composable(Destination.DASHBOARD.route) { DashboardScreen(state, requestEmergencyConfirmation) }
        composable(Destination.ACCOUNT.route) { AccountScreen(state) }
        composable(Destination.POSITIONS.route) {
            ReadOnlyScreen(
                "Positions",
                "Open-position data is read from the backend. No local position is invented.",
                Destination.POSITIONS.route,
                "/api/v1/positions",
                state,
                viewModel,
            )
        }
        composable(Destination.ORDERS.route) {
            ReadOnlyScreen(
                "Orders & fills",
                "Read-only broker order and fill monitoring. Android never sends orders.",
                Destination.ORDERS.route,
                "/api/v1/orders",
                state,
                viewModel,
            )
        }
        composable(Destination.SIGNALS.route) {
            ReadOnlyScreen(
                "Signals",
                "Signals, reasons, contradictions, and expiry are backend-audited data.",
                Destination.SIGNALS.route,
                "/api/v1/signals",
                state,
                viewModel,
            )
        }
        composable(Destination.BACKTEST.route) {
            ReadOnlyScreen(
                "Backtest",
                "Backtests are executed by the backend. Results must include assumptions and must not imply profitability.",
                Destination.BACKTEST.route,
                "/api/v1/performance",
                state,
                viewModel,
            )
        }
        composable(Destination.RISK.route) { RiskScreen(state, viewModel) }
        composable(Destination.AUTOMATION.route) { AutomationScreen(state, viewModel) }
        composable(Destination.AUDIT.route) {
            ReadOnlyScreen(
                "Audit log",
                "The backend is the source of timestamped signals, decisions, orders, fills, errors, and environment records.",
                Destination.AUDIT.route,
                "/api/v1/audit-log",
                state,
                viewModel,
            )
        }
        composable(Destination.HEALTH.route) { HealthScreen(state) }
        composable(Destination.SETTINGS.route) { SettingsScreen(state, viewModel) }
        composable(Destination.EMERGENCY.route) { EmergencyScreen(state, requestEmergencyConfirmation) }
    }
}

@Composable
private fun DashboardScreen(state: TradingUiState, requestEmergencyConfirmation: () -> Unit) {
    ScreenColumn {
        Text("Verified backend overview", style = MaterialTheme.typography.titleLarge)
        if (state.isLoading && state.account == null) LoadingPanel("Fetching account and automation state")
        AccountSummaryCard(state)
        AutomationSummaryCard(state.automation)
        ElevatedCard(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Server controls", style = MaterialTheme.typography.titleMedium)
                DetailRow("Current regime", "Awaiting backend market-regime data")
                DetailRow("Active strategy", "Server-managed")
                DetailRow("Last data update", state.account?.lastUpdated ?: "Not available")
                DetailRow("Backend health", state.health?.status ?: "Unknown")
                DetailRow("Kill switch", if (state.automation?.killSwitchActive == true) "ACTIVE" else "Not active / unknown")
            }
        }
        Card(
            colors = CardDefaults.cardColors(containerColor = LiveContainer),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(Modifier.padding(16.dp)) {
                Text("Emergency stop", fontWeight = FontWeight.Bold, color = LiveRed)
                Text("Immediately asks the backend to disable automated trading and activate its kill switch.")
                Spacer(Modifier.height(8.dp))
                Button(onClick = requestEmergencyConfirmation, colors = androidx.compose.material3.ButtonDefaults.buttonColors(containerColor = LiveRed)) {
                    Text("Activate emergency stop")
                }
            }
        }
    }
}

@Composable
private fun AccountScreen(state: TradingUiState) {
    ScreenColumn {
        Text("Verified account", style = MaterialTheme.typography.titleLarge)
        Text("Environment shown here is derived only from the server verification response.")
        AccountSummaryCard(state)
        state.environmentDetails?.let { details ->
            ElevatedCard(modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    DetailRow("Broker", details.broker ?: "Alpaca")
                    DetailRow("Account", details.accountIdMasked ?: "Masked account unavailable")
                    DetailRow("Account status", details.accountStatus ?: "Unknown")
                    DetailRow("Verified at", details.verifiedAt ?: "Not verified")
                    DetailRow("Trading blocked", details.tradingBlocked?.toString() ?: "Unknown")
                }
            }
        } ?: EmptyPanel("No verified environment was returned by the backend.")
    }
}

@Composable
private fun RiskScreen(state: TradingUiState, viewModel: TradingViewModel) {
    var riskJson by remember(state.riskConfig?.configurationFingerprint) {
        mutableStateOf(state.riskConfig?.config?.toString().orEmpty())
    }
    ScreenColumn {
        Text("Risk", style = MaterialTheme.typography.titleLarge)
        Text("Paper risk limits are validated by the backend and are required before paper automation can be enabled. This screen does not enable live trading.")
        ElevatedCard(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                DetailRow("Currently verified account", state.environment.name)
                DetailRow("Automation status", automationText(state.automation))
                DetailRow("Current account trading blocked", state.environmentDetails?.tradingBlocked?.toString() ?: "Unknown")
                DetailRow("Paper risk configuration", if (state.riskConfig?.complete == true) "Complete" else "Not configured")
            }
        }
        Text("Enter a JSON object with: max_risk_per_trade_pct, max_position_notional, max_instrument_exposure, max_portfolio_exposure, max_open_positions, max_daily_loss, max_weekly_loss, max_drawdown_pct, max_order_frequency_per_hour, max_slippage_bps, max_spread_bps, min_liquidity_usd, stale_data_seconds, news_blackout_minutes, and reduce_only.")
        OutlinedTextField(
            value = riskJson,
            onValueChange = { riskJson = it },
            label = { Text("Paper risk limits (JSON)") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 10,
        )
        Button(
            onClick = { viewModel.saveRiskConfig(riskJson) },
            enabled = !state.isActionInProgress && !state.backendOffline,
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (state.isActionInProgress) LoadingLabel("Saving") else Text("Save paper risk limits")
        }
        BackendPayloadPanel(Destination.RISK.route, "/api/v1/risk/config", state, viewModel)
    }
}

@Composable
private fun AutomationScreen(state: TradingUiState, viewModel: TradingViewModel) {
    var symbolsText by remember(state.watchlist?.symbols) {
        mutableStateOf(state.watchlist?.symbols?.joinToString(", ").orEmpty())
    }
    var confirmEnable by remember { mutableStateOf(false) }
    ScreenColumn {
        Text("Automation", style = MaterialTheme.typography.titleLarge)
        Text("Paper automation only. The backend controls strategy evaluation, risk checks, and any paper-account orders. Live trading is not enabled from this screen.")
        AutomationSummaryCard(state.automation)
        ElevatedCard(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Paper worker readiness", fontWeight = FontWeight.Bold)
                DetailRow("Heartbeat", if (state.automation?.workerHealthy == true) "Healthy" else "Not running / stale")
                DetailRow("Last seen", state.automation?.workerLastSeen ?: "Not available")
                Text("The worker must run continuously on the same persistent deployment. A sleeping free-tier web service cannot run this worker reliably.")
            }
        }
        OutlinedTextField(
            value = symbolsText,
            onValueChange = { symbolsText = it },
            label = { Text("Paper watchlist (comma-separated tickers)") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )
        OutlinedButton(
            onClick = { viewModel.savePaperWatchlist(symbolsText) },
            enabled = !state.isActionInProgress && !state.backendOffline,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Save paper watchlist")
        }
        if (state.automation?.enabled == true) {
            Button(
                onClick = viewModel::disableAutomation,
                enabled = !state.isActionInProgress && !state.backendOffline,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.isActionInProgress) LoadingLabel("Disabling") else Text("Disable automation")
            }
        } else {
            Text("Enabling requires a verified paper connection, complete paper risk limits, a saved watchlist, and a healthy worker heartbeat.")
            Button(
                onClick = { confirmEnable = true },
                enabled = !state.isActionInProgress && !state.backendOffline,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Enable paper automation")
            }
        }
        if (confirmEnable) {
            AlertDialog(
                onDismissRequest = { confirmEnable = false },
                title = { Text("Enable paper automation?") },
                text = { Text("This enables the server-side strategy worker for the verified paper account. It can submit simulated orders to the broker's paper environment, not a live account. The risk engine and kill switch remain in force.") },
                dismissButton = { TextButton(onClick = { confirmEnable = false }) { Text("Cancel") } },
                confirmButton = {
                    Button(onClick = {
                        confirmEnable = false
                        viewModel.enablePaperAutomation()
                    }, enabled = !state.isActionInProgress) { Text("Enable paper") }
                },
            )
        }
    }
}

@Composable
private fun HealthScreen(state: TradingUiState) {
    ScreenColumn {
        Text("System health", style = MaterialTheme.typography.titleLarge)
        if (state.backendOffline) {
            OfflineBanner()
            Text("Account and automation controls remain unavailable until the backend responds again.")
        }
        ElevatedCard(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                DetailRow("Status", state.health?.status ?: "No successful health response")
                DetailRow("Detail", state.health?.detail ?: state.health?.message ?: "Not available")
                DetailRow("Checked at", state.health?.timestamp ?: state.health?.checkedAt ?: "Not available")
            }
        }
        OutlinedButton(onClick = { /* outer top-bar refresh remains available */ }, enabled = false, modifier = Modifier.fillMaxWidth()) {
            Text("Use Refresh in the app bar")
        }
    }
}

@Composable
private fun SettingsScreen(state: TradingUiState, viewModel: TradingViewModel) {
    ScreenColumn {
        Text("Settings", style = MaterialTheme.typography.titleLarge)
        Text("Broker credentials are not stored on Android. Disconnecting removes the encrypted backend session token from this device.")
        ElevatedCard(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                DetailRow("Environment", state.environment.name)
                DetailRow("Backend session", "Encrypted with Android Keystore")
                DetailRow("Broker credentials", "Backend-only; not persisted on this device")
            }
        }
        OutlinedButton(onClick = viewModel::disconnect, modifier = Modifier.fillMaxWidth()) {
            Text("Disconnect and remove local session")
        }
    }
}

@Composable
private fun EmergencyScreen(state: TradingUiState, requestEmergencyConfirmation: () -> Unit) {
    ScreenColumn {
        Text("Emergency stop", style = MaterialTheme.typography.titleLarge, color = LiveRed)
        Text("Use this when you need the backend to stop automated trading immediately. It does not claim that a device-side action alone can stop broker activity.")
        DetailRow("Backend connectivity", if (state.backendOffline) "OFFLINE — cannot submit emergency request" else "Online / last known response")
        DetailRow("Kill-switch status", if (state.automation?.killSwitchActive == true) "ACTIVE" else "Not active / unknown")
        Button(
            onClick = requestEmergencyConfirmation,
            enabled = !state.isActionInProgress && !state.backendOffline,
            colors = androidx.compose.material3.ButtonDefaults.buttonColors(containerColor = LiveRed),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Request backend kill switch")
        }
    }
}

@Composable
private fun ReadOnlyScreen(
    title: String,
    description: String,
    screenKey: String,
    endpoint: String,
    state: TradingUiState,
    viewModel: TradingViewModel,
) {
    LaunchedEffect(screenKey) { viewModel.loadReadOnlyData(screenKey, endpoint) }
    ScreenColumn {
        Text(title, style = MaterialTheme.typography.titleLarge)
        Text(description)
        if (state.backendOffline) {
            OfflineBanner()
        }
        BackendPayloadContent(state.screenData[screenKey])
    }
}

@Composable
private fun BackendPayloadPanel(
    screenKey: String,
    endpoint: String,
    state: TradingUiState,
    viewModel: TradingViewModel,
) {
    LaunchedEffect(screenKey) { viewModel.loadReadOnlyData(screenKey, endpoint) }
    BackendPayloadContent(state.screenData[screenKey])
}

@Composable
private fun BackendPayloadContent(payload: com.alpacatalk.trading.data.RemoteScreenData?) {
    when {
        payload?.isLoading == true -> LoadingPanel("Loading backend-provided state")
        payload?.error != null -> EmptyPanel(payload.error)
        payload?.content != null -> Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Backend response", fontWeight = FontWeight.Bold)
                Text(payload.content, style = MaterialTheme.typography.bodySmall)
            }
        }
        else -> EmptyPanel("No data has been synchronised for this view yet. No sample trades are fabricated.")
    }
}

@Composable
private fun AccountSummaryCard(state: TradingUiState) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text("Account summary", style = MaterialTheme.typography.titleMedium)
            DetailRow("Account", state.account?.accountIdMasked ?: state.environmentDetails?.accountIdMasked ?: "Not available")
            DetailRow(
                "Status",
                state.account?.accountStatus ?: state.account?.status ?: state.environmentDetails?.accountStatus ?: "Unknown",
            )
            DetailRow("Equity", state.account?.equity ?: "Not available")
            DetailRow("Buying power", state.account?.buyingPower ?: "Not available")
            DetailRow("Open positions", state.account?.openPositions?.toString() ?: "Not available")
            DetailRow("Daily P&L", state.account?.dailyPnl ?: "Not available")
            DetailRow("Drawdown", state.account?.drawdown ?: "Not available")
        }
    }
}

@Composable
private fun AutomationSummaryCard(automation: AutomationStatusResponse?) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text("Automation", style = MaterialTheme.typography.titleMedium)
            DetailRow("Status", automationText(automation))
            DetailRow("Kill switch", if (automation?.killSwitchActive == true) "ACTIVE" else "Not active / unknown")
            DetailRow("Reason", automation?.reason ?: "Not available")
            DetailRow("Paper worker", if (automation?.workerHealthy == true) "Healthy" else "Unavailable")
            DetailRow("Last update", automation?.lastUpdated ?: "Not available")
        }
    }
}

@Composable
private fun VerifiedEnvironmentBanner(environment: VerifiedEnvironment) {
    val (text, color, contentColor) = when (environment) {
        VerifiedEnvironment.PAPER -> Triple(
            "PAPER TRADING — NO REAL MONEY IS BEING TRADED",
            PaperContainer,
            PaperBlue,
        )
        VerifiedEnvironment.LIVE -> Triple(
            "LIVE ACCOUNT — REAL ORDERS MAY BE SUBMITTED",
            LiveContainer,
            LiveRed,
        )
        VerifiedEnvironment.UNKNOWN -> Triple(
            "ENVIRONMENT NOT VERIFIED — CONNECT TO BACKEND",
            MaterialTheme.colorScheme.surfaceVariant,
            MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
    Surface(color = color, modifier = Modifier.fillMaxWidth()) {
        Text(
            text = text,
            color = contentColor,
            fontWeight = FontWeight.ExtraBold,
            style = MaterialTheme.typography.labelLarge,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
        )
    }
}

@Composable
private fun OfflineBanner() {
    Surface(color = OfflineContainer, modifier = Modifier.fillMaxWidth()) {
        Text(
            "BACKEND OFFLINE — AUTOMATION UNAVAILABLE",
            color = OfflineAmber,
            fontWeight = FontWeight.ExtraBold,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
        )
    }
}

@Composable
private fun ErrorOrInfo(state: TradingUiState) {
    val message = state.errorMessage ?: state.infoMessage ?: return
    val isError = state.errorMessage != null
    Surface(
        color = if (isError) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.secondaryContainer,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(
            message,
            color = if (isError) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onSecondaryContainer,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
        )
    }
}

@Composable
private fun SafetyDisclosure() {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text("Safety boundary", fontWeight = FontWeight.Bold)
            Text("The Android app is a monitoring and emergency-control client. Trading automation, risk checks, and any broker order submission run only on the backend.")
        }
    }
}

@Composable
private fun EmergencyConfirmation(inProgress: Boolean, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Activate emergency stop?") },
        text = { Text("This sends one request to the backend to disable automation and activate its kill switch. Existing broker-side orders may require backend reconciliation.") },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
        confirmButton = {
            Button(onClick = onConfirm, enabled = !inProgress, colors = androidx.compose.material3.ButtonDefaults.buttonColors(containerColor = LiveRed)) {
                Text("Activate stop")
            }
        },
    )
}

@Composable
private fun ScreenColumn(content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
        content = content,
    )
}

@Composable
private fun DetailRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Spacer(Modifier.width(12.dp))
        Text(value, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun EmptyPanel(message: String) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Text(message, modifier = Modifier.padding(16.dp), style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun LoadingPanel(message: String) {
    Row(modifier = Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(modifier = Modifier.height(22.dp).width(22.dp), strokeWidth = 2.dp)
        Spacer(Modifier.width(12.dp))
        Text(message)
    }
}

@Composable
private fun LoadingLabel(label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(modifier = Modifier.height(16.dp).width(16.dp), strokeWidth = 2.dp)
        Spacer(Modifier.width(8.dp))
        Text(label)
    }
}

private fun automationText(automation: AutomationStatusResponse?): String = when {
    automation == null -> "Unknown"
    automation.killSwitchActive == true -> "KILL SWITCH ACTIVE"
    automation.enabled == true -> automation.status ?: "Enabled"
    else -> automation.status ?: "Disabled"
}
