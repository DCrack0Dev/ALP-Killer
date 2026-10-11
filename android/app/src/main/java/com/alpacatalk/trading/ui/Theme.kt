package com.alpacatalk.trading.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val PaperBlue = Color(0xFF005E9C)
val PaperContainer = Color(0xFFD7EDFF)
val LiveRed = Color(0xFFB3261E)
val LiveContainer = Color(0xFFFFDAD6)
val OfflineAmber = Color(0xFF7A5200)
val OfflineContainer = Color(0xFFFFDEA6)

private val AppScheme = darkColorScheme(
    primary = Color(0xFF9DCAFF),
    onPrimary = Color(0xFF003258),
    primaryContainer = Color(0xFF004A77),
    onPrimaryContainer = Color(0xFFD1E4FF),
    secondary = Color(0xFFB9C8DA),
    background = Color(0xFF101417),
    surface = Color(0xFF101417),
    surfaceVariant = Color(0xFF3F484F),
    error = Color(0xFFFFB4AB),
)

@Composable
fun AlpacaTradingTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = AppScheme, content = content)
}
