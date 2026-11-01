package com.agy.pocket.ui

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.*
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

@SuppressLint("SetJavaScriptEnabled")
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RemoteControlScreen(
    url: String,
    title: String,
    onBack: () -> Unit
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    var webViewInstance by remember { mutableStateOf<WebView?>(null) }
    var isKeepAwake by remember { mutableStateOf(true) }

    // Manage screen keep awake
    DisposableEffect(isKeepAwake) {
        val window = (context as? Activity)?.window
        if (isKeepAwake) {
            window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        onDispose {
            window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }

    BackHandler {
        if (webViewInstance?.canGoBack() == true) {
            webViewInstance?.goBack()
        } else {
            onBack()
        }
    }

    fun injectQuickAction(action: String, promptText: String) {
        // 1. Copy to clipboard
        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val clip = ClipData.newPlainText("AGY Prompt", promptText)
        clipboard.setPrimaryClip(clip)

        // 2. If it's a local companion URL, send API request directly to companion server
        if (url.contains(":8765") || url.contains("/?token=")) {
            coroutineScope.launch {
                try {
                    withContext(Dispatchers.IO) {
                        val base = url.substringBefore("/?")
                        val token = if (url.contains("token=")) url.substringAfter("token=").substringBefore("&") else ""
                        val apiUrl = URL("$base/api/send_prompt")
                        val conn = apiUrl.openConnection() as HttpURLConnection
                        conn.requestMethod = "POST"
                        conn.setRequestProperty("Content-Type", "application/json")
                        if (token.isNotEmpty()) conn.setRequestProperty("X-Auth-Token", token)
                        conn.doOutput = true
                        
                        val jsonBody = """{"text": "$promptText", "auto_submit": true}"""
                        OutputStreamWriter(conn.outputStream).use { it.write(jsonBody) }
                        conn.responseCode
                        conn.disconnect()
                    }
                    Toast.makeText(context, "已发送至电脑: $promptText", Toast.LENGTH_SHORT).show()
                } catch (e: Exception) {
                    Toast.makeText(context, "已复制: $promptText", Toast.LENGTH_SHORT).show()
                }
            }
        } else {
            Toast.makeText(context, "已复制指令: $promptText\n可在输入框长按粘贴", Toast.LENGTH_SHORT).show()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            title,
                            fontWeight = FontWeight.Bold,
                            fontSize = 15.sp,
                            color = Color.White,
                            maxLines = 1
                        )
                        Text(
                            url,
                            fontSize = 11.sp,
                            color = Color(0xFF8B949E),
                            maxLines = 1
                        )
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Text("←", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                    }
                },
                actions = {
                    IconButton(onClick = { webViewInstance?.reload() }) {
                        Text("🔄", fontSize = 16.sp)
                    }
                    IconButton(onClick = {
                        isKeepAwake = !isKeepAwake
                        Toast.makeText(
                            context,
                            if (isKeepAwake) "已开启屏幕常亮" else "已恢复系统熄屏",
                            Toast.LENGTH_SHORT
                        ).show()
                    }) {
                        Text(if (isKeepAwake) "💡" else "💤", fontSize = 16.sp)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color(0xFF141721)
                )
            )
        },
        bottomBar = {
            // Horizontal Quick Actions Bar
            Surface(
                color = Color(0xFF1A1D27),
                shadowElevation = 8.dp
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 8.dp)
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    QuickChip("📐 /plan") { injectQuickAction("plan", "/plan ") }
                    QuickChip("🎯 /goal") { injectQuickAction("goal", "/goal ") }
                    QuickChip("✅ Proceed") { injectQuickAction("proceed", "Proceed") }
                    QuickChip("📦 /compact") { injectQuickAction("compact", "/compact") }
                    QuickChip("⚡ /boost") { injectQuickAction("boost", "/boost ") }
                    QuickChip("👍 好，继续") { injectQuickAction("continue", "好，继续执行") }
                    QuickChip("🔍 运行测试") { injectQuickAction("test", "运行测试验证") }
                }
            }
        },
        containerColor = Color(0xFF0F1117)
    ) { padding ->
        AndroidView(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            factory = { ctx ->
                WebView(ctx).apply {
                    layoutParams = ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT
                    )

                    settings.apply {
                        javaScriptEnabled = true
                        domStorageEnabled = true
                        databaseEnabled = true
                        setSupportZoom(true)
                        builtInZoomControls = true
                        displayZoomControls = false
                        useWideViewPort = true
                        loadWithOverviewMode = true
                        mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                        userAgentString = "$userAgentString AntigravityPocket/1.0"
                    }

                    // Enable cookies
                    CookieManager.getInstance().setAcceptCookie(true)
                    CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)

                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(
                            view: WebView?,
                            request: WebResourceRequest?
                        ): Boolean {
                            return false // Load inside this WebView
                        }
                    }

                    webChromeClient = WebChromeClient()
                    loadUrl(url)
                    webViewInstance = this
                }
            },
            update = {
                // Ensure instance reference is tracked
                webViewInstance = it
            }
        )
    }
}

@Composable
fun QuickChip(label: String, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        shape = RoundedCornerShape(16.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = Color(0xFF262C3D),
            contentColor = Color(0xFFE2E8F0)
        ),
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
        modifier = Modifier.height(34.dp)
    ) {
        Text(label, fontSize = 12.sp, fontWeight = FontWeight.Medium)
    }
}
