package com.voltarians.atlas_android_rfcomm

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.IOException
import java.util.UUID
import kotlin.concurrent.thread

class AtlasAndroidRfcommPlugin : FlutterPlugin,
    MethodChannel.MethodCallHandler, EventChannel.StreamHandler {
    private val sppUuid: UUID =
        UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
    private lateinit var context: Context
    private lateinit var methodChannel: MethodChannel
    private lateinit var eventChannel: EventChannel
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

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        eventSink = events
    }

    override fun onCancel(arguments: Any?) {
        eventSink = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        if (!hasConnectPermission()) {
            result.error(
                "PERMISSION",
                "Bluetooth connect permission has not been granted to OBD Atlas.",
                null)
            return
        }

        when (call.method) {
            "pairedDevices" -> {
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
                val address = call.argument<String>("address")
                if (address == null) {
                    result.error("ARGUMENT", "Missing Bluetooth address", null)
                } else {
                    connect(address, result)
                }
            }
            "write" -> {
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

    private fun hasConnectPermission(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true
        return context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) ==
            PackageManager.PERMISSION_GRANTED
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
