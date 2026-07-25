package com.realitymemory.glasses.wearable

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HeartRateMeasurementParserTest {
    @Test
    fun parsesEightBitHeartRate() {
        assertEquals(72, parseHeartRateMeasurement(byteArrayOf(0x00, 72)))
    }

    @Test
    fun parsesSixteenBitHeartRate() {
        assertEquals(300, parseHeartRateMeasurement(byteArrayOf(0x01, 0x2c, 0x01)))
    }

    @Test
    fun rejectsTruncatedMeasurements() {
        assertNull(parseHeartRateMeasurement(byteArrayOf()))
        assertNull(parseHeartRateMeasurement(byteArrayOf(0x01, 0x2c)))
    }
}
