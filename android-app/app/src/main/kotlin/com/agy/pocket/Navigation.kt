package com.agy.pocket

import androidx.compose.runtime.Composable
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.runtime.rememberNavBackStack
import androidx.navigation3.ui.NavDisplay
import com.agy.pocket.ui.HomeScreen
import com.agy.pocket.ui.RemoteControlScreen

@Composable
fun MainNavigation() {
    val backStack = rememberNavBackStack(Home)

    NavDisplay(
        backStack = backStack,
        onBack = { backStack.removeLastOrNull() },
        entryProvider = entryProvider {
            entry<Home> {
                HomeScreen(
                    onNavigateToRemote = { url, title ->
                        backStack.add(RemoteView(url = url, title = title))
                    }
                )
            }
            entry<RemoteView> { key ->
                RemoteControlScreen(
                    url = key.url,
                    title = key.title,
                    onBack = { backStack.removeLastOrNull() }
                )
            }
        }
    )
}
