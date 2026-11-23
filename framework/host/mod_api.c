/* (Triforce) The mods' side of the runtime: what a mod's built-in C calls (host/mod_api.h; nx2/code_hooks.py builds
   the mods' code in). Here: checked reads and writes of the game's memory, the log, and the mods' sounds, which are
   mixed over the game's output as the options' sounds are (menu_sound.c): after the game's limiter, before the Master
   volume (nn_audio.c render_frame calls hos_mod_sound_frame at each block).

   Sounds: a table of files by RomFS path, filled as mods ask (never emptied: a mod has a handful), and 16 voices. A
   voice is free while its place is negative. A player claims a free one (compare and swap, -1 to -2: players may be
   on several of the game's threads), sets its sound and gain, and stores place 0 last (release); the sound thread
   reads the place first (acquire) and alone moves it on and frees it. With all 16 playing the oldest is taken:
   the player asks for it (steal, the voice's number), and the sound thread, which alone may write a playing voice's
   place, restarts it at its next block. */
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <windows.h>   /* (GetTickCount64; host/posix has its own on Linux) */

#include "mod_api.h"
#include "menu_sound.h"   /* (hos_menu_sound_decode_long: the game's BWAV files) */

uint8_t *hos_fs_rom_file(const char *rel, uint64_t most, uint64_t *size);   /* nn_fs.c */

#define MOD_RATE 48000u            /* the mixer's rate (nn_audio.c RATE) */
#define MOD_SOUNDS 64
#define MOD_VOICES 16
#define MOD_SOUND_MOST (64u << 20) /* a sound file's most bytes */
#define MOD_SOUND_SECONDS 30u

/* ---- the mods built in (nx2/code_hooks.py writes the table when there are any; none: this one, weak) */
__attribute__((weak)) const char *const hos_mod_code_built[] = { 0 };

void hos_mod_code_report(void) {
    for (int i = 0; hos_mod_code_built[i]; i++)
        hos_log("mods: built with the code of %s (a mod's code can do what any program can)", hos_mod_code_built[i]);
}

/* ---- the game's memory */
int mod_readable(uint64_t a, uint64_t n) {
    if (a >= HOS_HEAP_BASE && a - HOS_HEAP_BASE < hos_heap_size) return n <= hos_heap_size - (a - HOS_HEAP_BASE);
    if (a >= hos_image_base && a < hos_image_end) return n <= hos_image_end - a;
    return 0;
}
uint8_t mod_ld8(uint64_t a) { return mod_readable(a, 1) ? *(const uint8_t *)GP(a) : 0; }
uint32_t mod_ld32(uint64_t a) { uint32_t v = 0; if (mod_readable(a, 4)) memcpy(&v, GP(a), 4); return v; }
uint64_t mod_ld64(uint64_t a) { uint64_t v = 0; if (mod_readable(a, 8)) memcpy(&v, GP(a), 8); return v; }
float mod_ldf(uint64_t a) { float v = 0; if (mod_readable(a, 4)) memcpy(&v, GP(a), 4); return v; }
void mod_st8(uint64_t a, uint8_t v) { if (mod_readable(a, 1)) *(uint8_t *)GP(a) = v; }
void mod_st32(uint64_t a, uint32_t v) { if (mod_readable(a, 4)) memcpy(GP(a), &v, 4); }
void mod_st64(uint64_t a, uint64_t v) { if (mod_readable(a, 8)) memcpy(GP(a), &v, 8); }
void mod_stf(uint64_t a, float v) { if (mod_readable(a, 4)) memcpy(GP(a), &v, 4); }

const char *mod_cstr(uint64_t a, char *out, int cap) {
    int n = 0;
    while (n < cap - 1 && mod_readable(a + (uint64_t)n, 1)) {
        const char ch = *(const char *)GP(a + (uint64_t)n);
        if (!ch) break;
        out[n++] = ch;
    }
    if (cap > 0) out[n] = 0;
    return out;
}
int mod_streq(uint64_t a, const char *text) {
    for (;; a++, text++) {
        if (!mod_readable(a, 1)) return 0;
        const char ch = *(const char *)GP(a);
        if (ch != *text) return 0;
        if (!ch) return 1;
    }
}

uint64_t mod_call(Ctx *c, void (*function)(Ctx *), uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3) {
    const Ctx saved = *c;
    c->x[0] = a0, c->x[1] = a1, c->x[2] = a2, c->x[3] = a3;
    function(c);
    const uint64_t result = c->x[0];
    *c = saved;
    return result;
}

uint64_t mod_time_ms(void) { return GetTickCount64(); }

void mod_log(const char *fmt, ...) {
    char line[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    hos_log("mod: %s", line);
}

/* ---- sounds */
typedef struct {
    char path[192];
    float *pcm;        /* interleaved stereo at MOD_RATE; NULL: not a sound (said once) */
    uint32_t frames;
} ModSound;
typedef struct {
    _Atomic int64_t place;             /* the next frame; -1 free, -2 claimed by a player */
    _Atomic(const ModSound *) sound;
    _Atomic uint32_t gain_bits;
    _Atomic uint64_t started;          /* the order the voices started in: the oldest is the one taken */
} ModVoice;

static ModSound sounds[MOD_SOUNDS];
static _Atomic int nsounds;
static atomic_flag sounds_lock = ATOMIC_FLAG_INIT;
static ModVoice voices[MOD_VOICES];
static _Atomic int voices_ready;
static _Atomic uint64_t starts;
static _Atomic int steal = -1;          /* a voice the sound thread is to start again with steal_sound, steal_gain */
static _Atomic(const ModSound *) steal_sound;
static _Atomic uint32_t steal_gain;

static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint32_t rd16(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8; }

/* A RIFF WAVE file's samples as interleaved stereo floats at MOD_RATE (a straight line between its samples where its
   rate is another), *frames of them; NULL when it is not one this plays. Nothing outside [file, file + size) is read */
static float *wav_decode(const uint8_t *file, uint64_t size, uint32_t *frames) {
    if (size < 12 || memcmp(file, "RIFF", 4) || memcmp(file + 8, "WAVE", 4)) return NULL;
    uint32_t format = 0, channels = 0, rate = 0, bits = 0;
    const uint8_t *data = NULL;
    uint64_t data_size = 0;
    for (uint64_t at = 12; at + 8 <= size;) {
        const uint64_t n = rd32(file + at + 4), body = at + 8;
        if (n > size - body) break;
        if (!memcmp(file + at, "fmt ", 4) && n >= 16) {
            format = rd16(file + body), channels = rd16(file + body + 2), rate = rd32(file + body + 4), bits = rd16(file + body + 14);
            if (format == 0xfffe && n >= 26) format = rd16(file + body + 24);   /* (extensible: the sub-format's first word) */
        } else if (!memcmp(file + at, "data", 4)) {
            data = file + body, data_size = n;
        }
        at = body + n + (n & 1);
    }
    const uint32_t bytes = bits / 8;
    if (!data || !rate || channels < 1 || channels > 2 || rate > 384000) return NULL;
    if (!((format == 1 && (bits == 8 || bits == 16 || bits == 24 || bits == 32)) || (format == 3 && bits == 32))) return NULL;
    const uint64_t n_in = data_size / ((uint64_t)bytes * channels);
    if (!n_in || n_in > (uint64_t)rate * MOD_SOUND_SECONDS) return NULL;
    const uint64_t n_out = n_in * MOD_RATE / rate;
    float *out = (float *)malloc((size_t)(n_out ? n_out : 1) * 2 * sizeof *out);
    if (!out) return NULL;
    for (uint64_t i = 0; i < n_out; i++) {
        const double t = (double)i * rate / MOD_RATE;
        const uint64_t i0 = (uint64_t)t, i1 = i0 + 1 < n_in ? i0 + 1 : i0;
        const float f = (float)(t - (double)i0);
        for (uint32_t ch = 0; ch < 2; ch++) {
            const uint32_t src = ch < channels ? ch : 0;
            float a, b;
            const uint8_t *pa = data + (i0 * channels + src) * bytes, *pb = data + (i1 * channels + src) * bytes;
            if (format == 3) memcpy(&a, pa, 4), memcpy(&b, pb, 4);
            else if (bits == 8) a = ((float)pa[0] - 128.0f) / 128.0f, b = ((float)pb[0] - 128.0f) / 128.0f;
            else if (bits == 16) a = (float)(int16_t)rd16(pa) / 32768.0f, b = (float)(int16_t)rd16(pb) / 32768.0f;
            else if (bits == 24) a = (float)((int32_t)(rd32(pa - 1) & 0xffffff00u)) / 2147483648.0f,
                                 b = (float)((int32_t)(rd32(pb - 1) & 0xffffff00u)) / 2147483648.0f;
            else a = (float)(int32_t)rd32(pa) / 2147483648.0f, b = (float)(int32_t)rd32(pb) / 2147483648.0f;
            out[i * 2 + ch] = a + (b - a) * f;
        }
    }
    *frames = (uint32_t)n_out;
    return out;
}

/* The table's sound of a path, read at its first use; NULL when it is none */
static const ModSound *sound_of(const char *path) {
    const int n = atomic_load_explicit(&nsounds, memory_order_acquire);
    for (int i = 0; i < n; i++)
        if (!strcmp(sounds[i].path, path)) return sounds[i].pcm ? &sounds[i] : NULL;
    if (strlen(path) >= sizeof sounds[0].path) return NULL;
    uint64_t size = 0;
    uint8_t *file = hos_fs_rom_file(path, MOD_SOUND_MOST, &size);
    uint32_t frames = 0;
    float *pcm = NULL;
    if (file) {
        pcm = wav_decode(file, size, &frames);
        if (!pcm) pcm = hos_menu_sound_decode_long(file, size, &frames, MOD_SOUND_SECONDS);
        free(file);
    }
    while (atomic_flag_test_and_set_explicit(&sounds_lock, memory_order_acquire)) { }
    const ModSound *found = NULL;
    int count = atomic_load_explicit(&nsounds, memory_order_relaxed), have = 0;
    for (int i = 0; i < count && !have; i++)   /* (another thread read the same file meanwhile: its copy stays) */
        if (!strcmp(sounds[i].path, path)) have = 1, found = sounds[i].pcm ? &sounds[i] : NULL;
    if (!have && count < MOD_SOUNDS) {
        snprintf(sounds[count].path, sizeof sounds[count].path, "%s", path);
        sounds[count].pcm = pcm, sounds[count].frames = frames;
        found = pcm ? &sounds[count] : NULL;
        pcm = NULL;
        atomic_store_explicit(&nsounds, count + 1, memory_order_release);
        if (found) hos_log("mod: sound %s: %.2f s", path, (double)frames / MOD_RATE);
        else hos_log("mod: sound %s: %s", path, file ? "not a .wav or .bwav file this plays" : "no such file in the game's files or a mod's");
    } else if (!have) {
        hos_log("mod: sound %s: not read, %d sounds are the most", path, MOD_SOUNDS);
    }
    atomic_flag_clear_explicit(&sounds_lock, memory_order_release);
    free(pcm);
    return found;
}

static void voices_init(void) {
    int no = 0;
    if (!atomic_compare_exchange_strong(&voices_ready, &no, 1)) return;
    for (int i = 0; i < MOD_VOICES; i++) atomic_store(&voices[i].place, -1);
    atomic_store(&voices_ready, 2);
}

int mod_sound_load(const char *romfs_path) { return sound_of(romfs_path) != NULL; }

int mod_sound_play(const char *romfs_path, float gain) {
    const ModSound *s = sound_of(romfs_path);
    if (!s) return 0;
    voices_init();
    uint32_t gain_bits;
    memcpy(&gain_bits, &gain, 4);
    int oldest = 0;
    uint64_t oldest_start = UINT64_MAX;
    for (int i = 0; i < MOD_VOICES; i++) {
        int64_t free_place = -1;
        if (atomic_compare_exchange_strong(&voices[i].place, &free_place, -2)) {
            atomic_store(&voices[i].sound, s);
            atomic_store(&voices[i].gain_bits, gain_bits);
            atomic_store(&voices[i].started, atomic_fetch_add(&starts, 1));
            atomic_store_explicit(&voices[i].place, 0, memory_order_release);
            return 1;
        }
        const uint64_t st = atomic_load(&voices[i].started);
        if (st < oldest_start) oldest_start = st, oldest = i;
    }
    atomic_store(&steal_sound, s);
    atomic_store(&steal_gain, gain_bits);
    atomic_store_explicit(&steal, oldest, memory_order_release);
    return 1;
}

/* The sound thread, at each block (nn_audio.c render_frame): the playing sounds added to the front left and right */
void hos_mod_sound_frame(float *left, float *right, uint32_t frames) {
    if (atomic_load_explicit(&voices_ready, memory_order_acquire) != 2) return;   /* (no mod has played anything) */
    const int taken = atomic_exchange_explicit(&steal, -1, memory_order_acquire);
    if (taken >= 0 && atomic_load(&voices[taken].place) >= 0) {
        atomic_store(&voices[taken].sound, atomic_load(&steal_sound));
        atomic_store(&voices[taken].gain_bits, atomic_load(&steal_gain));
        atomic_store(&voices[taken].started, atomic_fetch_add(&starts, 1));
        atomic_store(&voices[taken].place, 0);
    }
    for (int i = 0; i < MOD_VOICES; i++) {
        const int64_t place = atomic_load_explicit(&voices[i].place, memory_order_acquire);
        if (place < 0) continue;
        const ModSound *s = atomic_load(&voices[i].sound);
        const uint32_t gain_bits = atomic_load(&voices[i].gain_bits);
        float gain;
        memcpy(&gain, &gain_bits, 4);
        const uint64_t left_frames = (uint64_t)place < s->frames ? s->frames - (uint64_t)place : 0;
        const uint32_t n = left_frames < frames ? (uint32_t)left_frames : frames;
        const float *p = s->pcm + (uint64_t)place * 2;
        for (uint32_t k = 0; k < n; k++) left[k] += p[k * 2] * gain, right[k] += p[k * 2 + 1] * gain;
        atomic_store_explicit(&voices[i].place, (uint64_t)place + n >= s->frames ? -1 : place + (int64_t)n, memory_order_release);
    }
}
