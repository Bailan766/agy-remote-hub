package com.agy.pocket.data

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

data class SavedDevice(
    val id: String,
    val name: String,
    val url: String,
    val lastConnected: Long = System.currentTimeMillis(),
    val isOfficial: Boolean = false
) {
    fun toJson(): JSONObject {
        val obj = JSONObject()
        obj.put("id", id)
        obj.put("name", name)
        obj.put("url", url)
        obj.put("lastConnected", lastConnected)
        obj.put("isOfficial", isOfficial)
        return obj
    }

    companion object {
        fun fromJson(obj: JSONObject): SavedDevice {
            return SavedDevice(
                id = obj.optString("id", ""),
                name = obj.optString("name", "Unknown"),
                url = obj.optString("url", ""),
                lastConnected = obj.optLong("lastConnected", System.currentTimeMillis()),
                isOfficial = obj.optBoolean("isOfficial", false)
            )
        }
    }
}

class DeviceStorage(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("agy_pocket_devices", Context.MODE_PRIVATE)

    fun getDevices(): List<SavedDevice> {
        val raw = prefs.getString("saved_list", null) ?: return defaultDevices()
        val list = mutableListOf<SavedDevice>()
        try {
            val array = JSONArray(raw)
            for (i in 0 until array.length()) {
                val obj = array.getJSONObject(i)
                list.add(SavedDevice.fromJson(obj))
            }
        } catch (e: Exception) {
            return defaultDevices()
        }
        return if (list.isEmpty()) defaultDevices() else list
    }

    fun saveDevice(device: SavedDevice) {
        val current = getDevices().filter { it.url != device.url }.toMutableList()
        current.add(0, device)
        val array = JSONArray()
        for (d in current) {
            array.put(d.toJson())
        }
        prefs.edit().putString("saved_list", array.toString()).apply()
    }

    fun deleteDevice(id: String) {
        val updated = getDevices().filter { it.id != id }
        val array = JSONArray()
        for (d in updated) {
            array.put(d.toJson())
        }
        prefs.edit().putString("saved_list", array.toString()).apply()
    }

    private fun defaultDevices(): List<SavedDevice> {
        return listOf(
            SavedDevice(
                id = "official_google",
                name = "Google 官方 Remote Control",
                url = "https://antigravity.google",
                isOfficial = true
            )
        )
    }
}
