package com.example.mobile

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val channelName = "enterprise_rag/files"
    private val settingsChannelName = "enterprise_rag/settings"
    private val pickDocumentRequest = 42
    private var pendingResult: MethodChannel.Result? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName).setMethodCallHandler { call, result ->
            when (call.method) {
                "pickDocument" -> {
                    pendingResult = result
                    val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = "*/*"
                        putExtra(
                            Intent.EXTRA_MIME_TYPES,
                            arrayOf(
                                "application/pdf",
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                "application/msword",
                                "text/plain"
                            )
                        )
                    }
                    startActivityForResult(intent, pickDocumentRequest)
                }
                else -> result.notImplemented()
            }
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, settingsChannelName).setMethodCallHandler { call, result ->
            val prefs = getSharedPreferences("enterprise_rag_mobile", Context.MODE_PRIVATE)
            when (call.method) {
                "read" -> {
                    result.success(prefs.all)
                }
                "write" -> {
                    val key = call.argument<String>("key")
                    val value = call.argument<Any>("value")
                    if (key == null) {
                        result.error("invalid_key", "Missing settings key.", null)
                        return@setMethodCallHandler
                    }
                    val editor = prefs.edit()
                    when (value) {
                        is Boolean -> editor.putBoolean(key, value)
                        is String -> editor.putString(key, value)
                        else -> editor.putString(key, value?.toString() ?: "")
                    }
                    editor.apply()
                    result.success(null)
                }
                "remove" -> {
                    val keys = call.argument<List<String>>("keys") ?: emptyList()
                    val editor = prefs.edit()
                    keys.forEach { editor.remove(it) }
                    editor.apply()
                    result.success(null)
                }
                "clear" -> {
                    prefs.edit().clear().apply()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != pickDocumentRequest) {
            return
        }
        val result = pendingResult ?: return
        pendingResult = null
        if (resultCode != Activity.RESULT_OK || data?.data == null) {
            result.success(null)
            return
        }
        val uri = data.data as Uri
        try {
            val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() }
            if (bytes == null) {
                result.error("file_read_failed", "Could not read selected file.", null)
                return
            }
            result.success(
                mapOf(
                    "name" to displayName(uri),
                    "bytes" to bytes
                )
            )
        } catch (error: Exception) {
            result.error("file_read_failed", error.message, null)
        }
    }

    private fun displayName(uri: Uri): String {
        contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (index >= 0 && cursor.moveToFirst()) {
                return cursor.getString(index)
            }
        }
        return "document"
    }
}
