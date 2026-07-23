package com.realitymemory.cxrlprobe

import android.content.Intent
import android.graphics.BitmapFactory
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.weight
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    private val controller: CxrProbeController
        get() = (application as ProbeApplication).controller

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        controller.inspectCompanionApp(this)
        setContent {
            MaterialTheme {
                val state by controller.state.collectAsState()
                ProbeScreen(
                    state = state,
                    onCheckApp = { controller.inspectCompanionApp(this) },
                    onAuthorize = { controller.requestAuthorization(this) },
                    onConnect = controller::connect,
                    onCapture = { controller.takePhoto() },
                    onStartSchedule = controller::startScheduledCapture,
                    onStopSchedule = controller::stopScheduledCapture,
                    onDisconnect = controller::disconnect
                )
            }
        }
    }

    @Deprecated("Required by the Rokid CXR-L authorization callback contract")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == CxrProbeController.REQUEST_CODE_AUTH) {
            controller.parseAuthorizationResult(resultCode, data)
        }
    }
}

@Composable
private fun ProbeScreen(
    state: ProbeState,
    onCheckApp: () -> Unit,
    onAuthorize: () -> Unit,
    onConnect: () -> Unit,
    onCapture: () -> Unit,
    onStartSchedule: () -> Unit,
    onStopSchedule: () -> Unit,
    onDisconnect: () -> Unit
) {
    val green = Color(0xFF167A4B)
    val amber = Color(0xFFB55A00)
    val ink = Color(0xFF17212B)
    val paper = Color(0xFFF4F6F5)

    Surface(color = paper, modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Text(
                text = "Reality CXR-L Probe",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
                color = ink
            )
            Text(
                text = state.status,
                style = MaterialTheme.typography.bodyLarge,
                color = if (state.captureReady) green else amber
            )

            StatusPanel(state)

            Text("Setup", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Button(
                onClick = onCheckApp,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = ink),
                shape = RoundedCornerShape(4.dp)
            ) {
                Text("1. Check Rokid AI App")
            }
            Button(
                onClick = onAuthorize,
                enabled = state.companionInstalled,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = green),
                shape = RoundedCornerShape(4.dp)
            ) {
                Text("2. Request glasses permissions")
            }
            Button(
                onClick = onConnect,
                enabled = state.authenticated,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = green),
                shape = RoundedCornerShape(4.dp)
            ) {
                Text("3. Connect and open CustomView")
            }

            HorizontalDivider()
            Text("Capture", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Button(
                    onClick = onCapture,
                    enabled = state.captureReady,
                    modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(4.dp)
                ) {
                    Text(if (state.takingPhoto) "Capturing..." else "Capture once")
                }
                Button(
                    onClick = if (state.scheduledCaptureEnabled) onStopSchedule else onStartSchedule,
                    enabled = state.captureReady || state.scheduledCaptureEnabled,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (state.scheduledCaptureEnabled) amber else ink
                    ),
                    shape = RoundedCornerShape(4.dp)
                ) {
                    Text(if (state.scheduledCaptureEnabled) "Stop timer" else "Start 30s timer")
                }
            }

            state.lastImageBytes?.let { bytes ->
                val bitmap = remember(bytes) {
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
                }
                bitmap?.let {
                    Image(
                        bitmap = it,
                        contentDescription = "Last glasses capture",
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(220.dp)
                            .background(Color.Black),
                        contentScale = ContentScale.Fit
                    )
                }
            }
            Text(
                text = state.lastCaptureSummary,
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace
            )

            OutlinedButton(
                onClick = onDisconnect,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(4.dp)
            ) {
                Text("Disconnect")
            }

            HorizontalDivider()
            Text("Recent events", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            state.recentEvents.forEach { event ->
                Text(
                    text = event,
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace
                )
            }
            Spacer(Modifier.size(8.dp))
        }
    }
}

@Composable
private fun StatusPanel(state: ProbeState) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color.White, RoundedCornerShape(4.dp))
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        StatusLine("Rokid AI App", state.companionInstalled)
        StatusLine("Runtime authorization", state.authenticated)
        StatusLine("CXR link", state.cxrConnected)
        StatusLine("Glasses Bluetooth", state.glassBluetoothConnected)
        StatusLine("CustomView", state.customViewOpened)
        Text(
            text = "Wearing: ${state.wearing?.toString() ?: "unknown"} | Captures: ${state.captureCount}",
            style = MaterialTheme.typography.bodyMedium
        )
    }
}

@Composable
private fun StatusLine(label: String, ready: Boolean) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium)
        Text(
            text = if (ready) "READY" else "WAIT",
            color = if (ready) Color(0xFF167A4B) else Color(0xFF9A4B00),
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.labelMedium
        )
    }
}
