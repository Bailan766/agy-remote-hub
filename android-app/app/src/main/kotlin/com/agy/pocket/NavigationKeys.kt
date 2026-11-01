package com.agy.pocket

import androidx.navigation3.runtime.NavKey
import kotlinx.serialization.Serializable

@Serializable
data object Home : NavKey

@Serializable
data class RemoteView(val url: String, val title: String = "Antigravity") : NavKey
