package com.agy.pocket.ui

import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.agy.pocket.data.DeviceStorage
import com.agy.pocket.data.SavedDevice
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import java.text.SimpleDateFormat
import java.util.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onNavigateToRemote: (url: String, title: String) -> Unit
) {
    val context = LocalContext.current
    val storage = remember { DeviceStorage(context) }
    var devices by remember { mutableStateOf(storage.getDevices()) }
    var inputUrl by remember { mutableStateOf("") }

    val scanLauncher = rememberLauncherForActivityResult(ScanContract()) { result ->
        if (result.contents != null) {
            val scannedUrl = result.contents.trim()
            handleConnect(scannedUrl, storage, context) { url, name ->
                devices = storage.getDevices()
                onNavigateToRemote(url, name)
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            modifier = Modifier
                                .size(28.dp)
                                .clip(RoundedCornerShape(6.dp))
                                .background(Color(0xFF4E80EE)),
                            contentAlignment = Alignment.Center
                        ) {
                            Text("⚡", fontSize = 16.sp)
                        }
                        Spacer(modifier = Modifier.width(10.dp))
                        Text(
                            "AGY Pocket",
                            fontWeight = FontWeight.Bold,
                            fontSize = 20.sp,
                            color = Color.White
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color(0xFF141721)
                )
            )
        },
        containerColor = Color(0xFF0F1117)
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // Scanner Action Card
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF1A1D27))
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(20.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            "手机远程控制电脑",
                            fontSize = 18.sp,
                            fontWeight = FontWeight.Bold,
                            color = Color.White
                        )
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            "扫描电脑桌面配套启动器或 Antigravity 的二维码",
                            fontSize = 13.sp,
                            color = Color(0xFF959EA9)
                        )
                        Spacer(modifier = Modifier.height(18.dp))

                        Button(
                            onClick = {
                                val options = ScanOptions().apply {
                                    setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                                    setPrompt("请对准电脑屏幕上的连接二维码")
                                    setCameraId(0)
                                    setBeepEnabled(true)
                                    setBarcodeImageEnabled(false)
                                    setOrientationLocked(false)
                                }
                                scanLauncher.launch(options)
                            },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(50.dp),
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF4E80EE))
                        ) {
                            Text("📷 扫描连接二维码", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }

            // Manual Input Card
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF1A1D27))
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            "手动输入或粘贴远程地址",
                            fontSize = 14.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = Color(0xFF959EA9)
                        )
                        Spacer(modifier = Modifier.height(10.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            OutlinedTextField(
                                value = inputUrl,
                                onValueChange = { inputUrl = it },
                                placeholder = {
                                    Text(
                                        "http://192.168.x.x:8765 或官方链接",
                                        fontSize = 13.sp,
                                        color = Color(0xFF6B7280)
                                    )
                                },
                                modifier = Modifier
                                    .weight(1f)
                                    .padding(end = 8.dp),
                                singleLine = true,
                                shape = RoundedCornerShape(10.dp),
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = Color(0xFF4E80EE),
                                    unfocusedBorderColor = Color(0xFF2E3549),
                                    focusedTextColor = Color.White,
                                    unfocusedTextColor = Color.White
                                )
                            )
                            Button(
                                onClick = {
                                    val trimmed = inputUrl.trim()
                                    if (trimmed.isNotEmpty()) {
                                        handleConnect(trimmed, storage, context) { url, name ->
                                            devices = storage.getDevices()
                                            onNavigateToRemote(url, name)
                                        }
                                    }
                                },
                                shape = RoundedCornerShape(10.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF2E3549)),
                                modifier = Modifier.height(52.dp)
                            ) {
                                Text("连接", color = Color.White)
                            }
                        }
                    }
                }
            }

            // Saved Devices & History Header
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        "常用设备与连接历史",
                        fontSize = 15.sp,
                        fontWeight = FontWeight.Bold,
                        color = Color.White
                    )
                    Text(
                        "${devices.size} 台设备",
                        fontSize = 12.sp,
                        color = Color(0xFF959EA9)
                    )
                }
            }

            // Devices list
            items(devices, key = { it.id }) { device ->
                DeviceItemView(
                    device = device,
                    onClick = {
                        storage.saveDevice(device.copy(lastConnected = System.currentTimeMillis()))
                        onNavigateToRemote(device.url, device.name)
                    },
                    onDelete = {
                        storage.deleteDevice(device.id)
                        devices = storage.getDevices()
                    }
                )
            }
        }
    }
}

@Composable
fun DeviceItemView(
    device: SavedDevice,
    onClick: () -> Unit,
    onDelete: () -> Unit
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onClick() },
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0xFF1E2230))
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(42.dp)
                    .clip(CircleShape)
                    .background(if (device.isOfficial) Color(0xFF233876) else Color(0xFF1F4E3D)),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    if (device.isOfficial) "🌐" else "💻",
                    fontSize = 20.sp
                )
            }
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    device.name,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 15.sp,
                    color = Color.White,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    device.url,
                    fontSize = 12.sp,
                    color = Color(0xFF8B949E),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(2.dp))
                val sdf = SimpleDateFormat("MM-dd HH:mm", Locale.getDefault())
                Text(
                    "最近访问: ${sdf.format(Date(device.lastConnected))}",
                    fontSize = 10.sp,
                    color = Color(0xFF5A6372)
                )
            }
            IconButton(onClick = onDelete) {
                Text("✕", color = Color(0xFF6B7280), fontSize = 16.sp)
            }
        }
    }
}

private fun handleConnect(
    rawUrl: String,
    storage: DeviceStorage,
    context: android.content.Context,
    onSuccess: (url: String, name: String) -> Unit
) {
    var validUrl = rawUrl
    if (!validUrl.startsWith("http://") && !validUrl.startsWith("https://")) {
        validUrl = "http://$validUrl"
    }

    val isOfficial = validUrl.contains("antigravity.google")
    val deviceName = if (isOfficial) {
        "Google 官方 Remote Control"
    } else {
        val host = try {
            java.net.URI(validUrl).host ?: "我的电脑"
        } catch (e: Exception) {
            "我的电脑"
        }
        "电脑端 ($host)"
    }

    val newDevice = SavedDevice(
        id = UUID.randomUUID().toString(),
        name = deviceName,
        url = validUrl,
        lastConnected = System.currentTimeMillis(),
        isOfficial = isOfficial
    )
    storage.saveDevice(newDevice)
    Toast.makeText(context, "正在连接: $deviceName", Toast.LENGTH_SHORT).show()
    onSuccess(validUrl, deviceName)
}
