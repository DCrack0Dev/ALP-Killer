package com.alpacatalk.trading

import com.alpacatalk.trading.data.ApiException
import com.alpacatalk.trading.data.BackendUrlPolicy
import com.alpacatalk.trading.data.VerifiedEnvironment
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test

class EnvironmentSafetyTest {
    @Test
    fun paperAndLiveLabelsRequireServerVerificationTimestamp() {
        assertEquals(
            VerifiedEnvironment.UNKNOWN,
            VerifiedEnvironment.fromServer("paper", verifiedAt = null),
        )
        assertEquals(
            VerifiedEnvironment.PAPER,
            VerifiedEnvironment.fromServer("paper", verifiedAt = "2026-10-11T10:00:00Z"),
        )
        assertEquals(
            VerifiedEnvironment.LIVE,
            VerifiedEnvironment.fromServer("LIVE", verifiedAt = "2026-10-11T10:00:00Z"),
        )
    }

    @Test
    fun nonLoopbackCleartextBackendIsRejected() {
        try {
            BackendUrlPolicy.normalize("http://trading.example.test")
            fail("Cleartext non-loopback host must be rejected")
        } catch (_: ApiException) {
            // Expected: production and debug builds must not permit arbitrary HTTP.
        }
    }

    @Test
    fun httpsBackendIsAccepted() {
        assertEquals(
            "https://trading.example.test",
            BackendUrlPolicy.normalize("https://trading.example.test/"),
        )
    }
}
