package com.alpacatalk.trading.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.nio.ByteBuffer
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Stores only the backend session token. The AES key is non-exportable and held in Android Keystore.
 * Broker API keys/secrets never reach this class and are never written to device storage.
 */
class KeystoreSessionStore(context: Context) {
    private val tokenFile = File(context.filesDir, "backend_session.bin")

    fun save(token: String) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encrypted = cipher.doFinal(token.encodeToByteArray())
        val iv = cipher.iv
        require(iv.size <= 255) { "Unexpected GCM IV size" }
        val payload = ByteBuffer.allocate(1 + iv.size + encrypted.size)
            .put(iv.size.toByte())
            .put(iv)
            .put(encrypted)
            .array()
        tokenFile.outputStream().use { stream ->
            stream.write(payload)
            stream.flush()
        }
    }

    fun read(): String? {
        return try {
            if (!tokenFile.exists()) {
                null
            } else {
                val payload = tokenFile.readBytes()
                val ivLength = payload.firstOrNull()?.toInt()?.and(0xff) ?: 0
                if (ivLength == 0 || payload.size <= ivLength + 1) {
                    null
                } else {
                    val iv = payload.copyOfRange(1, ivLength + 1)
                    val encrypted = payload.copyOfRange(ivLength + 1, payload.size)
                    val cipher = Cipher.getInstance(TRANSFORMATION)
                    cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(TAG_BITS, iv))
                    cipher.doFinal(encrypted).decodeToString()
                }
            }
        } catch (_: Exception) {
            // A stale key or corrupt token is safely invalidated; sensitive values are never logged.
            clear()
            null
        }
    }

    fun clear() {
        tokenFile.delete()
    }

    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "alpaca_trading_backend_session_v1"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val TAG_BITS = 128
    }
}

/** Backend address is non-secret; it is kept separately from the encrypted token. */
class BackendUrlStore(context: Context) {
    private val urlFile = File(context.filesDir, "backend_url.txt")

    fun save(url: String) = urlFile.writeText(url)
    fun read(): String? = urlFile.takeIf(File::exists)?.readText()?.trim()?.ifBlank { null }
    fun clear() = urlFile.delete()
}
