package com.alpacatalk.trading.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/** Server API models deliberately contain no raw broker credentials or persistent secret fields. */
@Serializable
data class AuthSessionRequest(
    val passphrase: String,
)

@Serializable
data class AuthSessionResponse(
    @SerialName("access_token") val accessToken: String? = null,
    @SerialName("expires_in_seconds") val expiresInSeconds: Int? = null,
)

@Serializable
data class ConnectionValidateRequest(
    @SerialName("api_key") val apiKey: String,
    @SerialName("api_secret") val apiSecret: String,
    @SerialName("requested_environment") val requestedEnvironment: String? = null,
)

@Serializable
data class KillSwitchRequest(
    val reason: String,
)

@Serializable
data class ConnectionValidationResponse(
    val broker: String? = null,
    val environment: String? = null,
    @SerialName("account_id_masked") val accountIdMasked: String? = null,
    @SerialName("account_status") val accountStatus: String? = null,
    @SerialName("verified_at") val verifiedAt: String? = null,
    @SerialName("automation_enabled") val automationEnabled: Boolean? = null,
    @SerialName("trading_blocked") val tradingBlocked: Boolean? = null,
)

@Serializable
data class AccountResponse(
    @SerialName("account_id_masked") val accountIdMasked: String? = null,
    @SerialName("account_status") val accountStatus: String? = null,
    val status: String? = null,
    val equity: String? = null,
    @SerialName("buying_power") val buyingPower: String? = null,
    val cash: String? = null,
    @SerialName("daily_pnl") val dailyPnl: String? = null,
    val drawdown: String? = null,
    @SerialName("open_positions") val openPositions: Int? = null,
    @SerialName("last_updated") val lastUpdated: String? = null,
)

@Serializable
data class EnvironmentResponse(
    val broker: String? = null,
    val environment: String? = null,
    @SerialName("account_id_masked") val accountIdMasked: String? = null,
    @SerialName("account_status") val accountStatus: String? = null,
    @SerialName("trading_blocked") val tradingBlocked: Boolean? = null,
    @SerialName("automation_enabled") val automationEnabled: Boolean? = null,
    @SerialName("verified_at") val verifiedAt: String? = null,
)

@Serializable
data class AutomationStatusResponse(
    val enabled: Boolean? = null,
    val status: String? = null,
    val message: String? = null,
    @SerialName("kill_switch_active") val killSwitchActive: Boolean? = null,
    @SerialName("last_updated") val lastUpdated: String? = null,
    @SerialName("worker_healthy") val workerHealthy: Boolean? = null,
    @SerialName("worker_last_seen") val workerLastSeen: String? = null,
    val reason: String? = null,
)

@Serializable
data class RiskConfigResponse(
    val environment: String? = null,
    val complete: Boolean = false,
    val config: JsonObject? = null,
    @SerialName("configuration_fingerprint") val configurationFingerprint: String? = null,
)

@Serializable
data class WatchlistResponse(
    val environment: String? = null,
    val symbols: List<String> = emptyList(),
)

@Serializable
data class WatchlistUpdateRequest(
    val symbols: List<String>,
)

@Serializable
data class HealthResponse(
    val status: String? = null,
    val detail: String? = null,
    val message: String? = null,
    val timestamp: String? = null,
    @SerialName("automation_available") val automationAvailable: Boolean? = null,
    @SerialName("checked_at") val checkedAt: String? = null,
)

@Serializable
data class ActionResponse(
    val status: String? = null,
    val detail: String? = null,
    val message: String? = null,
    @SerialName("kill_switch_active") val killSwitchActive: Boolean? = null,
)

enum class VerifiedEnvironment {
    UNKNOWN,
    PAPER,
    LIVE;

    companion object {
        /**
         * A paper/live label is emitted only when the backend supplies a verification timestamp.
         * This intentionally prevents a local setting or a credential-entry hint from being trusted.
         */
        fun fromServer(environment: String?, verifiedAt: String?): VerifiedEnvironment = when {
            verifiedAt.isNullOrBlank() -> UNKNOWN
            environment.equals("paper", ignoreCase = true) -> PAPER
            environment.equals("live", ignoreCase = true) -> LIVE
            else -> UNKNOWN
        }
    }
}

enum class ConnectionState {
    DISCONNECTED,
    SESSION_READY,
    VALIDATING,
    CONNECTED,
}

/** A redacted, backend-provided read-only screen payload; it never holds raw credentials or tokens. */
data class RemoteScreenData(
    val isLoading: Boolean = false,
    val content: String? = null,
    val error: String? = null,
)

data class TradingUiState(
    val connectionState: ConnectionState = ConnectionState.DISCONNECTED,
    val isLoading: Boolean = false,
    val isActionInProgress: Boolean = false,
    val backendOffline: Boolean = false,
    val errorMessage: String? = null,
    val infoMessage: String? = null,
    val environment: VerifiedEnvironment = VerifiedEnvironment.UNKNOWN,
    val environmentDetails: EnvironmentResponse? = null,
    val account: AccountResponse? = null,
    val automation: AutomationStatusResponse? = null,
    val riskConfig: RiskConfigResponse? = null,
    val watchlist: WatchlistResponse? = null,
    val health: HealthResponse? = null,
    val screenData: Map<String, RemoteScreenData> = emptyMap(),
) {
    val isConnected: Boolean get() = connectionState == ConnectionState.CONNECTED
}
