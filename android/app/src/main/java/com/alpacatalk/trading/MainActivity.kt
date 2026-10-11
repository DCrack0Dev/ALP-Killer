package com.alpacatalk.trading

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import com.alpacatalk.trading.ui.AlpacaTradingApp
import com.alpacatalk.trading.ui.AlpacaTradingTheme

class MainActivity : ComponentActivity() {
    private val tradingViewModel: TradingViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Credential-entry UI and account data are excluded from screenshots and recent-app previews.
        window.setFlags(
            WindowManager.LayoutParams.FLAG_SECURE,
            WindowManager.LayoutParams.FLAG_SECURE,
        )
        enableEdgeToEdge()
        setContent {
            AlpacaTradingTheme {
                AlpacaTradingApp(tradingViewModel)
            }
        }
    }
}
