package com.voltarians.atlas_android_rfcomm

import android.Manifest
import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.PluginRegistry
import java.io.IOException
import java.util.UUID
import kotlin.concurrent.thread

class AtlasAndroidRfcommPlugin : FlutterPlugin,
    MethodChannel.MethodCallHandler,
    EventChannel.StreamHandler,
    ActivityAware,
    PluginRegistry.RequestPermissionsResultListener {
    private val sppUuid: UUID =
        UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
    private val permissionRequestCode = 4817

    private lateinit var context: Context
    private lateinit var methodChannel: MethodChannel
    private lateinit var eventChannel: EventChannel
    private var activity: Activity? = null
    private var activityBinding: ActivityPluginBinding? = null
    private var permissionResult: MethodChannel.Result? = null
    private var socket: BluetoothSocket? = null
    private var eventSink: EventChannel.EventSink? = null
    private val mainHandler = Handler(Looper.getMainLooper())

    private val adapter: BluetoothAdapter?
        get() = (context.getSystemService(Context.BLUETOOTH_SERVICE)
                as BluetoothManager).adapter

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        context = binding.applicationContext
        methodChannel = MethodChannel(
            binding.binaryMessenger, "obd_atlas/android_rfcomm")
        eventChannel = EventChannel(
            binding.binaryMessenger, "obd_atlas/android_rfcomm_bytes")
        methodChannel.setMethodCallHandler(this)
        eventChannel.setStreamHandler(this)
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        methodChannel.setMethodCallHandler(null)
        eventChannel.setStreamHandler(null)
        closeSocket()
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
        activityBinding = binding
        binding.addRequestPermissionsResultListener(this)
    }

    override fun onDetachedFromActivityForConfigChanges() {
        detachActivity()
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) {
        onAttachedToActivity(binding)
    }

    override fun onDetachedFromActivity() {
        detachActivity()
    }

    private fun detachActivity() {
        activityBinding?.removeRequestPermissionsResultListener(this)
        activityBinding = null
        activity = null
        permissionResult?.error(
            "PERMISSION",
            "Bluetooth permission request was interrupted.",
            null)
        permissionResult = null
    }

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        eventSink = events
    }

    override fun onCancel(arguments: Any?) {
        eventSink = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "requestConnectPermission" -> requestConnectPermission(result)
            "pairedDevices" -> {
                if (!requireConnectPermission(result)) return
                try {
                    val devices = adapter?.bondedDevices.orEmpty().map {
                        mapOf(
                            "name" to (it.name ?: ""),
                            "address" to it.address)
                    }.sortedBy { it["name"] ?: "" }
                    result.success(devices)
                } catch (error: SecurityException) {
                    result.error("PERMISSION", error.message, null)
                }
            }
            "connect" -> {
                if (!requireConnectPermission(result)) return
                val address = call.argument<String>("address")
                if (address == null) {
                    result.error("ARGUMENT", "Missing Bluetooth address", null)
                } else {
                    connect(address, result)
                }
            }
            "write" -> {
                if (!requireConnectPermission(result)) return
                val bytes = call.arguments as? ByteArray
                if (bytes == null) {
                    result.error("ARGUMENT", "Missing bytes", null)
                } else {
                    write(bytes, result)
                }
            }
            "close" -> {
                closeSocket()
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    private fun requestConnectPermission(result: MethodChannel.Result) {
        if (hasConnectPermission()) {
            result.success(true)
            return
        }

        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            result.success(true)
            return
        }

        val currentActivity = activity
        if (currentActivity == null) {
            result.error(
                "PERMISSION",
                "Android activity is unavailable for Bluetooth permission request.",
                null)
            return
        }

        if (permissionResult != null) {
            result.error(
                "PERMISSION",
                "A Bluetooth permission request is already in progress.",
                null)
            return
        }

        permissionResult = result
        currentActivity.requestPermissions(
            arrayOf(Manifest.permission.BLUETOOTH_CONNECT),
            permissionRequestCode)
    }

    private fun requireConnectPermission(result: MethodChannel.Result): Boolean {
        if (hasConnectPermission()) return true
        result.error(
            "PERMISSION",
            "Bluetooth connect permission has not been granted to OBD Atlas.",
            null)
        return false
    }

    private fun hasConnectPermission(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true
        return context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) ==
            PackageManager.PERMISSION_GRANTED
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ): Boolean {
        if (requestCode != permissionRequestCode) return false

        val pending = permissionResult ?: return true
        permissionResult = null
        val granted = grantResults.isNotEmpty() &&
            grantResults[0] == PackageManager.PERMISSION_GRANTED
        pending.success(granted)
        return true
    }

    private fun connect(address: String, result: MethodChannel.Result) {
        thread(name = "Atlas-vLinker-RFCOMM-connect") {
            try {
                closeSocket()
                adapter?.cancelDiscovery()
                val device = adapter?.getRemoteDevice(address)
                    ?: throw IOException("Bluetooth is unavailable")
                val connected =
                    device.createRfcommSocketToServiceRecord(sppUuid)
                connected.connect()
                socket = connected
                startReader(connected)
                mainHandler.post { result.success(null) }
            } catch (error: Exception) {
                closeSocket()
                mainHandler.post {
                    result.error("CONNECT", error.message, null)
                }
            }
        }
    }

    private fun startReader(connected: BluetoothSocket) =
        thread(name = "Atlas-vLinker-RFCOMM-read") {
            val buffer = ByteArray(4096)
            try {
                while (connected.isConnected) {
                    val count = connected.inputStream.read(buffer)
                    if (count < 0) break
                    val packet = buffer.copyOf(count)
                    mainHandler.post { eventSink?.success(packet) }
                }
            } catch (error: Exception) {
                mainHandler.post {
                    eventSink?.error("READ", error.message, null)
                }
            } finally {
                closeSocket()
            }
        }

    private fun write(bytes: ByteArray, result: MethodChannel.Result) {
        thread(name = "Atlas-vLinker-RFCOMM-write") {
            try {
                val connected = socket ?: throw IOException("Not connected")
                connected.outputStream.write(bytes)
                connected.outputStream.flush()
                mainHandler.post { result.success(null) }
            } catch (error: Exception) {
                mainHandler.post {
                    result.error("WRITE", error.message, null)
                }
            }
        }
    }

    @Synchronized
    private fun closeSocket() {
        try {
            socket?.close()
        } catch (_: Exception) {
        }
        socket = null
    }
}
