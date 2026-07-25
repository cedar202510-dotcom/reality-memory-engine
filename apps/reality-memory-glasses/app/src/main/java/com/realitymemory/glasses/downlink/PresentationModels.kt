package com.realitymemory.glasses.downlink

enum class PresentationIntent {
    ANSWER,
    REMINDER,
    TASK,
    CONSUMABLE,
    PRIVACY,
    SYSTEM,
}

enum class PresentationInteraction {
    NONE,
    DISMISS,
    ACKNOWLEDGE,
    COMPLETE_TASK,
    ADD_TO_SHOPPING_LIST,
}

data class DownlinkPresentation(
    val messageId: String,
    val intent: PresentationIntent,
    val title: String,
    val body: String?,
    val speechText: String?,
    val interaction: PresentationInteraction,
    val actionId: String?,
    val allowText: Boolean,
    val allowTts: Boolean,
    val expiresAtEpochMs: Long,
    val priority: String,
    val fallbackIntent: String? = null,
)
