package com.alpacatalk.trading.data

import com.alpacatalk.trading.BuildConfig
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.android.Android
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.HttpRequestBuilder
import io.ktor.client.request.accept
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import java.net.URI
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/** Errors retain only HTTP status/detail and must never include request secrets. */
class ApiException(message: String, val statusCode: Int? = null) : Exception(message)

/**
 * HTTPS client for the server-controlled trading API. There is intentionally no order-submission
 * method: paper automation is explicitly enabled through guarded backend controls; the backend
 * remains the sole authority for every broker order.
 */
class ApiClient private constructor(
    private val baseUrl: String,
    private val sessionToken: String?,
) : AutoCloseable {
    private val client = HttpClient(Android) {
        install(ContentNegotiation) {
            json(JSON)
        }
        install(HttpTimeout) {
            connectTimeoutMillis = 10_000
            requestTimeoutMillis = 20_000
            socketTimeoutMillis = 20_000
        }
        expectSuccess = false
    }

    suspend fun createSession(passphrase: String): AuthSessionResponse =
        decode(client.post(url("/api/v1/auth/session")) {
            contentType(ContentType.Application.Json)
            accept(ContentType.Application.Json)
            setBody(AuthSessionRequest(passphrase))
        })

    suspend fun validateConnection(apiKey: String, apiSecret: String): ConnectionValidationResponse =
        decode(client.post(url("/api/v1/connections/validate")) {
            authorized()
            contentType(ContentType.Application.Json)
            accept(ContentType.Application.Json)
            setBody(ConnectionValidateRequest(apiKey, apiSecret))
        })

    suspend fun account(): AccountResponse = decode(client.get(url("/api/v1/account")) { authorized() })

    suspend fun environment(): EnvironmentResponse =
        decode(client.get(url("/api/v1/account/environment")) { authorized() })

    suspend fun automationStatus(): AutomationStatusResponse =
        decode(client.get(url("/api/v1/automation/status")) { authorized() })

    suspend fun riskConfig(): RiskConfigResponse =
        decode(client.get(url("/api/v1/risk/config?environment=paper")) { authorized() })

    suspend fun updateRiskConfig(config: JsonObject): RiskConfigResponse =
        decode(client.put(url("/api/v1/risk/config?environment=paper")) {
            authorized()
            contentType(ContentType.Application.Json)
            setBody(config)
        })

    suspend fun watchlist(): WatchlistResponse =
        decode(client.get(url("/api/v1/automation/watchlist")) { authorized() })

    suspend fun updateWatchlist(symbols: List<String>): WatchlistResponse =
        decode(client.put(url("/api/v1/automation/watchlist")) {
            authorized()
            contentType(ContentType.Application.Json)
            setBody(WatchlistUpdateRequest(symbols))
        })

    suspend fun enablePaperAutomation(): AutomationStatusResponse =
        decode(client.post(url("/api/v1/automation/enable-paper")) { authorized() })

    suspend fun disableAutomation(environment: String): ActionResponse =
        decode(client.post(url("/api/v1/automation/disable?environment=$environment")) {
            authorized()
        })

    suspend fun activateKillSwitch(): ActionResponse =
        decode(client.post(url("/api/v1/kill-switch/activate")) {
            authorized()
            contentType(ContentType.Application.Json)
            setBody(KillSwitchRequest("Android emergency stop requested"))
        })

    suspend fun health(): HealthResponse = decode(client.get(url("/api/v1/health")) { authorized() })

    /** Best-effort server-side disconnect, followed by guaranteed local session deletion by caller. */
    suspend fun disconnect(environment: String): ActionResponse =
        decode(client.post(url("/api/v1/connections/disconnect?environment=$environment")) {
            authorized()
        })

    /**
     * Retrieves a documented read-only API resource for a detail screen. This deliberately accepts
     * only a relative endpoint chosen in client source and does not expose an order-write method.
     */
    suspend fun readOnlyPayload(relativePath: String): JsonElement {
        require(relativePath.startsWith("/api/v1/")) { "Unexpected API path" }
        val response = client.get(url(relativePath)) {
            authorized()
            accept(ContentType.Application.Json)
        }
        if (response.status.value !in 200..299) {
            throw ApiException("Request failed with HTTP ${response.status.value}.", response.status.value)
        }
        return JSON.parseToJsonElement(response.bodyAsText())
    }

    private fun HttpRequestBuilder.authorized() {
        sessionToken?.let { header(HttpHeaders.Authorization, "Bearer $it") }
    }

    private fun url(path: String): String = "$baseUrl$path"

    private suspend inline fun <reified T> decode(response: HttpResponse): T {
        if (response.status.value !in 200..299) {
            // Do not parse an error body: a faulty server must never echo a submitted secret into UI.
            throw ApiException("Request failed with HTTP ${response.status.value}.", response.status.value)
        }
        return response.body()
    }

    override fun close() = client.close()

    companion object {
        val JSON = Json {
            ignoreUnknownKeys = true
            isLenient = true
        }

        fun create(baseUrl: String, sessionToken: String?): ApiClient {
            val normalized = BackendUrlPolicy.normalize(baseUrl)
            return ApiClient(normalized, sessionToken)
        }
    }
}

object BackendUrlPolicy {
    /** Accept TLS endpoints, with debug-only HTTP constrained strictly to loopback development. */
    fun normalize(rawUrl: String): String {
        val candidate = rawUrl.trim().removeSuffix("/")
        val uri = try {
            URI(candidate)
        } catch (_: Exception) {
            throw ApiException("Enter a valid backend URL.")
        }
        val host = uri.host?.lowercase()
        val isLoopback = host == "localhost" || host == "127.0.0.1" || host == "::1"
        val https = uri.scheme.equals("https", ignoreCase = true)
        val debugLoopbackHttp = BuildConfig.ALLOW_LOCALHOST_HTTP &&
            uri.scheme.equals("http", ignoreCase = true) && isLoopback
        if ((https || debugLoopbackHttp) && host != null && uri.userInfo == null && uri.query == null && uri.fragment == null) {
            return candidate
        }
        throw ApiException("Use an HTTPS backend URL. Debug builds allow HTTP only for localhost.")
    }
}
