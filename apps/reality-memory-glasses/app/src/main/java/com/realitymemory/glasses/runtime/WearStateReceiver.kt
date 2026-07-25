package com.realitymemory.glasses.runtime

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.realitymemory.glasses.MainActivity

class WearStateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED -> startMonitor(context)

            ACTION_TAKE_STATUS_CHANGED -> {
                val worn = intent.getStringExtra(EXTRA_TAKE_STATE) == "1"
                startRuntime(context, worn, "TAKE_STATUS")
                if (worn) showDisclosure(context)
            }

            ACTION_LEG_STATUS_CHANGED -> {
                val unfolded = intent.getStringExtra(EXTRA_LEG_STATE) == "1"
                if (!unfolded) startRuntime(context, false, "LEGS_FOLDED")
            }
        }
    }

    private fun startMonitor(context: Context) {
        ContextCompat.startForegroundService(
            context,
            Intent(context, RealityRuntimeService::class.java)
                .setAction(RealityRuntimeService.ACTION_ARM_MONITOR),
        )
    }

    private fun startRuntime(context: Context, worn: Boolean, source: String) {
        val serviceIntent = Intent(context, RealityRuntimeService::class.java)
            .setAction(RealityRuntimeService.ACTION_WEAR_CHANGED)
            .putExtra(RealityRuntimeService.EXTRA_WORN, worn)
            .putExtra(RealityRuntimeService.EXTRA_WEAR_SOURCE, source)
        ContextCompat.startForegroundService(context, serviceIntent)
    }

    private fun showDisclosure(context: Context) {
        runCatching {
            context.startActivity(
                Intent(context, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                    .putExtra(MainActivity.EXTRA_OPENED_FROM_WEAR, true),
            )
        }
    }

    companion object {
        const val ACTION_TAKE_STATUS_CHANGED = "com.rokid.sprite.ACTION_TAKE_STATUS_CHANGED"
        const val ACTION_LEG_STATUS_CHANGED = "com.rokid.sprite.ACTION_LEG_STATUS_CHANGED"
        private const val EXTRA_TAKE_STATE = "glasses_take_state"
        private const val EXTRA_LEG_STATE = "glasses_leg_state"
    }
}
