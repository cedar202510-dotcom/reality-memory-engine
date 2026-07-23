package com.realitymemory.cxrlprobe

import android.app.Application

class ProbeApplication : Application() {
    lateinit var controller: CxrProbeController
        private set

    override fun onCreate() {
        super.onCreate()
        controller = CxrProbeController(this)
    }
}
