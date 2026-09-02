#include "audio2face/audio2face.h"
#include "audio2x/cuda_utils.h"

#include <windows.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <wrl/client.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <cwctype>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr std::size_t kSampleRate = 16000;
constexpr std::size_t kFrameRate = 60;
constexpr double kDefaultMaxDurationSeconds = 60.0;

enum class ModelType { Regression, Diffusion };

std::string pathUtf8(const fs::path& path) { return path.u8string(); }

std::string jsonEscape(const std::wstring& value) {
  std::ostringstream escaped;
  escaped << std::hex << std::setfill('0');
  for (const wchar_t c : value) {
    switch (c) {
      case '\\': escaped << "\\\\"; break;
      case '"': escaped << "\\\""; break;
      case '\b': escaped << "\\b"; break;
      case '\f': escaped << "\\f"; break;
      case '\n': escaped << "\\n"; break;
      case '\r': escaped << "\\r"; break;
      case '\t': escaped << "\\t"; break;
      default:
        if (c < 0x20 || c > 0x7e) {
          escaped << "\\u" << std::setw(4) << static_cast<unsigned int>(c);
        } else {
          escaped << static_cast<char>(c);
        }
    }
  }
  return escaped.str();
}

constexpr std::array<const char*, 52> kArkitChannels = {
    "eyeBlinkLeft",       "eyeLookDownLeft",  "eyeLookInLeft",       "eyeLookOutLeft",
    "eyeLookUpLeft",      "eyeSquintLeft",    "eyeWideLeft",         "eyeBlinkRight",
    "eyeLookDownRight",   "eyeLookInRight",   "eyeLookOutRight",     "eyeLookUpRight",
    "eyeSquintRight",     "eyeWideRight",     "jawForward",          "jawLeft",
    "jawRight",           "jawOpen",          "mouthClose",          "mouthFunnel",
    "mouthPucker",        "mouthLeft",        "mouthRight",          "mouthSmileLeft",
    "mouthSmileRight",    "mouthFrownLeft",   "mouthFrownRight",     "mouthDimpleLeft",
    "mouthDimpleRight",   "mouthStretchLeft", "mouthStretchRight",   "mouthRollLower",
    "mouthRollUpper",     "mouthShrugLower",  "mouthShrugUpper",     "mouthPressLeft",
    "mouthPressRight",    "mouthLowerDownLeft", "mouthLowerDownRight", "mouthUpperUpLeft",
    "mouthUpperUpRight",  "browDownLeft",     "browDownRight",       "browInnerUp",
    "browOuterUpLeft",    "browOuterUpRight", "cheekPuff",           "cheekSquintLeft",
    "cheekSquintRight",   "noseSneerLeft",    "noseSneerRight",      "tongueOut",
};

template <typename T> struct Destroyer {
  void operator()(T* value) const {
    if (value != nullptr) {
      value->Destroy();
    }
  }
};

template <typename T> using SdkPtr = std::unique_ptr<T, Destroyer<T>>;

template <typename T> SdkPtr<T> sdkPtr(T* value) { return SdkPtr<T>(value); }

void check(std::error_code error, const char* operation) {
  if (error) {
    throw std::runtime_error(std::string(operation) + ": " + error.message());
  }
}

template <typename T> T readValue(std::istream& stream) {
  T value{};
  stream.read(reinterpret_cast<char*>(&value), sizeof(value));
  if (!stream) {
    throw std::runtime_error("Unexpected end of WAV file");
  }
  return value;
}

std::vector<float> loadWav(const fs::path& path) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream) {
    throw std::runtime_error("Cannot open WAV file: " + pathUtf8(path));
  }

  char riff[4]{};
  char wave[4]{};
  stream.read(riff, 4);
  (void)readValue<std::uint32_t>(stream);
  stream.read(wave, 4);
  if (std::memcmp(riff, "RIFF", 4) != 0 || std::memcmp(wave, "WAVE", 4) != 0) {
    throw std::runtime_error("Input is not a RIFF/WAVE file");
  }

  std::uint16_t format = 0;
  std::uint16_t channels = 0;
  std::uint32_t sampleRate = 0;
  std::uint16_t bitsPerSample = 0;
  std::vector<std::uint8_t> data;

  while (stream && (format == 0 || data.empty())) {
    char chunkId[4]{};
    stream.read(chunkId, 4);
    if (!stream) {
      break;
    }
    const auto chunkSize = readValue<std::uint32_t>(stream);
    const auto chunkStart = stream.tellg();

    if (std::memcmp(chunkId, "fmt ", 4) == 0) {
      format = readValue<std::uint16_t>(stream);
      channels = readValue<std::uint16_t>(stream);
      sampleRate = readValue<std::uint32_t>(stream);
      (void)readValue<std::uint32_t>(stream);
      (void)readValue<std::uint16_t>(stream);
      bitsPerSample = readValue<std::uint16_t>(stream);
    } else if (std::memcmp(chunkId, "data", 4) == 0) {
      data.resize(chunkSize);
      stream.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
    }

    stream.clear();
    stream.seekg(chunkStart + static_cast<std::streamoff>(chunkSize + (chunkSize & 1U)));
  }

  if (channels == 0 || sampleRate == 0 || data.empty()) {
    throw std::runtime_error("WAV file is missing fmt or data chunks");
  }
  if (format != 1 && format != 3) {
    throw std::runtime_error("Only PCM and IEEE float WAV files are supported");
  }

  const std::size_t bytesPerSample = bitsPerSample / 8;
  if (bytesPerSample == 0 || data.size() % (bytesPerSample * channels) != 0) {
    throw std::runtime_error("Invalid WAV sample layout");
  }

  const std::size_t frameCount = data.size() / (bytesPerSample * channels);
  std::vector<float> mono(frameCount, 0.0f);
  for (std::size_t frame = 0; frame < frameCount; ++frame) {
    double sum = 0.0;
    for (std::size_t channel = 0; channel < channels; ++channel) {
      const auto* sample = data.data() + (frame * channels + channel) * bytesPerSample;
      float value = 0.0f;
      if (format == 3 && bitsPerSample == 32) {
        std::memcpy(&value, sample, sizeof(value));
      } else if (format == 1 && bitsPerSample == 16) {
        std::int16_t raw{};
        std::memcpy(&raw, sample, sizeof(raw));
        value = static_cast<float>(raw / 32768.0);
      } else if (format == 1 && bitsPerSample == 24) {
        std::int32_t raw = static_cast<std::int32_t>(sample[0]) |
                           (static_cast<std::int32_t>(sample[1]) << 8) |
                           (static_cast<std::int32_t>(sample[2]) << 16);
        if ((raw & 0x00800000) != 0) {
          raw |= static_cast<std::int32_t>(0xFF000000);
        }
        value = static_cast<float>(raw / 8388608.0);
      } else if (format == 1 && bitsPerSample == 32) {
        std::int32_t raw{};
        std::memcpy(&raw, sample, sizeof(raw));
        value = static_cast<float>(raw / 2147483648.0);
      } else {
        throw std::runtime_error("Unsupported WAV bit depth");
      }
      sum += value;
    }
    mono[frame] = static_cast<float>(sum / channels);
  }

  if (sampleRate == kSampleRate) {
    return mono;
  }

  const double ratio = static_cast<double>(sampleRate) / kSampleRate;
  const auto outputSize = static_cast<std::size_t>(std::ceil(mono.size() / ratio));
  std::vector<float> resampled(outputSize);
  for (std::size_t i = 0; i < outputSize; ++i) {
    const double source = i * ratio;
    const auto left = std::min(static_cast<std::size_t>(source), mono.size() - 1);
    const auto right = std::min(left + 1, mono.size() - 1);
    const float fraction = static_cast<float>(source - left);
    resampled[i] = mono[left] + (mono[right] - mono[left]) * fraction;
  }
  return resampled;
}

void checkHr(HRESULT result, const char* operation) {
  if (FAILED(result)) {
    std::ostringstream message;
    message << operation << " failed (HRESULT 0x" << std::hex
            << static_cast<unsigned long>(result) << ')';
    throw std::runtime_error(message.str());
  }
}

class MediaFoundationSession {
 public:
  MediaFoundationSession() {
    const HRESULT comResult = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    comInitialized_ = SUCCEEDED(comResult);
    if (FAILED(comResult) && comResult != RPC_E_CHANGED_MODE) {
      checkHr(comResult, "Initialize COM");
    }
    checkHr(MFStartup(MF_VERSION), "Start Media Foundation");
    mfInitialized_ = true;
  }

  ~MediaFoundationSession() {
    if (mfInitialized_) MFShutdown();
    if (comInitialized_) CoUninitialize();
  }

 private:
  bool comInitialized_ = false;
  bool mfInitialized_ = false;
};

std::vector<float> loadWithMediaFoundation(const fs::path& path) {
  using Microsoft::WRL::ComPtr;
  MediaFoundationSession session;

  ComPtr<IMFSourceReader> reader;
  checkHr(MFCreateSourceReaderFromURL(path.c_str(), nullptr, &reader),
          "Open audio file");
  constexpr DWORD kAllStreams = static_cast<DWORD>(MF_SOURCE_READER_ALL_STREAMS);
  constexpr DWORD kAudioStream = static_cast<DWORD>(MF_SOURCE_READER_FIRST_AUDIO_STREAM);
  checkHr(reader->SetStreamSelection(kAllStreams, FALSE),
          "Disable source streams");
  checkHr(reader->SetStreamSelection(kAudioStream, TRUE),
          "Select audio stream");

  ComPtr<IMFMediaType> outputType;
  checkHr(MFCreateMediaType(&outputType), "Create output audio type");
  checkHr(outputType->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio), "Set audio type");
  checkHr(outputType->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_Float), "Set float audio format");
  checkHr(outputType->SetUINT32(MF_MT_AUDIO_NUM_CHANNELS, 1), "Set mono audio");
  checkHr(outputType->SetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND,
                                static_cast<UINT32>(kSampleRate)),
          "Set audio sample rate");
  checkHr(outputType->SetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, 32), "Set audio bit depth");
  checkHr(reader->SetCurrentMediaType(kAudioStream, nullptr, outputType.Get()),
          "Configure audio decoder");

  std::vector<float> samples;
  while (true) {
    DWORD flags = 0;
    ComPtr<IMFSample> sample;
    checkHr(reader->ReadSample(kAudioStream, 0, nullptr, &flags, nullptr, &sample),
            "Decode audio sample");
    if ((flags & MF_SOURCE_READERF_ENDOFSTREAM) != 0) break;
    if (!sample) continue;

    ComPtr<IMFMediaBuffer> buffer;
    checkHr(sample->ConvertToContiguousBuffer(&buffer), "Read decoded audio buffer");
    BYTE* bytes = nullptr;
    DWORD byteCount = 0;
    checkHr(buffer->Lock(&bytes, nullptr, &byteCount), "Lock decoded audio buffer");
    if (byteCount % sizeof(float) != 0) {
      buffer->Unlock();
      throw std::runtime_error("Decoder returned an invalid float audio buffer");
    }
    const auto* begin = reinterpret_cast<const float*>(bytes);
    samples.insert(samples.end(), begin, begin + byteCount / sizeof(float));
    checkHr(buffer->Unlock(), "Unlock decoded audio buffer");
  }
  if (samples.empty()) {
    throw std::runtime_error("Audio decoder produced no samples. The codec may be unsupported.");
  }
  return samples;
}

std::vector<float> loadAudio(const fs::path& path) {
  std::wstring extension = path.extension().wstring();
  std::transform(extension.begin(), extension.end(), extension.begin(), ::towlower);
  return extension == L".wav" ? loadWav(path) : loadWithMediaFoundation(path);
}

struct Frame {
  std::int64_t timestamp{};
  std::vector<float> weights;
};

struct CallbackState {
  std::vector<Frame> frames;
  std::error_code error;
};

void onFrame(void* userdata, const nva2f::IBlendshapeExecutor::HostResults& results,
             std::error_code error) {
  auto& state = *static_cast<CallbackState*>(userdata);
  if (error) {
    state.error = error;
    return;
  }
  Frame frame;
  frame.timestamp = static_cast<std::int64_t>(results.timeStampCurrentFrame);
  frame.weights.assign(results.weights.Data(), results.weights.Data() + results.weights.Size());
  state.frames.emplace_back(std::move(frame));
}

std::vector<Frame> infer(const fs::path& modelPath, const std::vector<float>& audio,
                         ModelType modelType, std::size_t identityIndex) {
  SdkPtr<nva2f::IBlendshapeExecutorBundle> bundle;
  if (modelType == ModelType::Diffusion) {
    bundle = sdkPtr(nva2f::ReadDiffusionBlendshapeSolveExecutorBundle(
        1, pathUtf8(modelPath).c_str(), nva2f::IGeometryExecutor::ExecutionOption::Skin,
        false, identityIndex, true, nullptr, nullptr));
  } else {
    bundle = sdkPtr(nva2f::ReadRegressionBlendshapeSolveExecutorBundle(
        1, pathUtf8(modelPath).c_str(), nva2f::IGeometryExecutor::ExecutionOption::Skin,
        false, kFrameRate, 1, nullptr, nullptr));
  }
  if (!bundle) {
    throw std::runtime_error("Unable to load Audio2Face blendshape model: " + pathUtf8(modelPath));
  }

  auto& emotion = bundle->GetEmotionAccumulator(0);
  std::vector<float> neutralEmotion(emotion.GetEmotionSize(), 0.0f);
  check(emotion.Accumulate(0, nva2x::HostTensorFloatConstView{
                                  neutralEmotion.data(), neutralEmotion.size()},
                           bundle->GetCudaStream().Data()),
        "Accumulate emotion");
  check(emotion.Close(), "Close emotion accumulator");

  auto& accumulator = bundle->GetAudioAccumulator(0);
  check(accumulator.Accumulate(nva2x::HostTensorFloatConstView{audio.data(), audio.size()},
                               bundle->GetCudaStream().Data()),
        "Accumulate audio");
  check(accumulator.Close(), "Close audio accumulator");

  auto& executor = bundle->GetExecutor();
  CallbackState callback;
  check(executor.SetResultsCallback(onFrame, &callback), "Set results callback");
  while (nva2x::GetNbReadyTracks(executor) > 0) {
    check(executor.Execute(nullptr), "Execute inference");
  }
  check(executor.Wait(0), "Wait for inference");
  check(callback.error, "Blendshape callback");
  if (callback.frames.empty()) {
    throw std::runtime_error("Audio2Face produced no animation frames");
  }
  if (callback.frames.front().weights.size() != kArkitChannels.size()) {
    throw std::runtime_error("Unexpected blendshape channel count: " +
                             std::to_string(callback.frames.front().weights.size()));
  }
  return callback.frames;
}

void writeJson(const fs::path& output, const fs::path& audioPath,
               const std::vector<Frame>& frames) {
  std::ofstream stream(output, std::ios::binary);
  if (!stream) {
    throw std::runtime_error("Cannot create output file: " + pathUtf8(output));
  }
  stream << std::setprecision(8);
  stream << "{\n  \"schema\": \"a2f-blendshapes-v1\",\n";
  stream << "  \"exportFps\": " << kFrameRate << ",\n";
  stream << "  \"numPoses\": " << kArkitChannels.size() << ",\n";
  stream << "  \"numFrames\": " << frames.size() << ",\n";
  stream << "  \"facsNames\": [";
  for (std::size_t i = 0; i < kArkitChannels.size(); ++i) {
    if (i != 0) stream << ',';
    stream << "\"" << kArkitChannels[i] << "\"";
  }
  stream << "],\n";
  stream << "  \"weightMat\": [\n";
  for (std::size_t i = 0; i < frames.size(); ++i) {
    stream << "    [";
    for (std::size_t j = 0; j < frames[i].weights.size(); ++j) {
      if (j != 0) stream << ',';
      stream << frames[i].weights[j];
    }
    stream << "]" << (i + 1 == frames.size() ? "\n" : ",\n");
  }
  stream << "  ],\n";
  stream << "  \"trackPath\": \"" << jsonEscape(fs::absolute(audioPath).wstring()) << "\",\n";
  stream << "  \"fps\": " << kFrameRate << ",\n";
  stream << "  \"source\": \"" << jsonEscape(audioPath.filename().wstring())
         << "\",\n  \"channels\": [";
  for (std::size_t i = 0; i < kArkitChannels.size(); ++i) {
    if (i != 0) stream << ',';
    stream << "\"" << kArkitChannels[i] << "\"";
  }
  stream << "],\n  \"frames\": [\n";
  for (std::size_t i = 0; i < frames.size(); ++i) {
    stream << "    {\"t\":" << frames[i].timestamp << ",\"w\":[";
    for (std::size_t j = 0; j < frames[i].weights.size(); ++j) {
      if (j != 0) stream << ',';
      stream << frames[i].weights[j];
    }
    stream << "]}" << (i + 1 == frames.size() ? "\n" : ",\n");
  }
  stream << "  ]\n}\n";
}

void printUsage() {
  std::cerr << "Usage: a2f_blender_exporter --model <model.json> --audio <input audio> "
               "--output <animation.json> --model-type <regression|diffusion> "
               "[--identity <0|1|2>] [--max-duration <seconds>]\n";
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  try {
    fs::path model;
    fs::path audio;
    fs::path output;
    ModelType modelType = ModelType::Regression;
    std::size_t identityIndex = 2;
    double maxDurationSeconds = kDefaultMaxDurationSeconds;
    for (int i = 1; i < argc; ++i) {
      const std::wstring arg = argv[i];
      if ((arg == L"--model" || arg == L"--audio" || arg == L"--output" ||
           arg == L"--model-type" || arg == L"--identity" ||
           arg == L"--max-duration") && i + 1 < argc) {
        const fs::path value = argv[++i];
        if (arg == L"--model") model = value;
        if (arg == L"--audio") audio = value;
        if (arg == L"--output") output = value;
        if (arg == L"--model-type") {
          if (value == L"regression") modelType = ModelType::Regression;
          else if (value == L"diffusion") modelType = ModelType::Diffusion;
          else throw std::runtime_error("Model type must be regression or diffusion");
        }
        if (arg == L"--identity") identityIndex = std::stoul(value.wstring());
        if (arg == L"--max-duration") maxDurationSeconds = std::stod(value.wstring());
      } else if (arg == L"--help" || arg == L"-h") {
        printUsage();
        return 0;
      } else {
        throw std::runtime_error("Unknown or incomplete argument: " + pathUtf8(fs::path(arg)));
      }
    }
    if (model.empty() || audio.empty() || output.empty()) {
      printUsage();
      return 2;
    }
    if (!fs::is_regular_file(model)) throw std::runtime_error("Model file does not exist");
    if (!fs::is_regular_file(audio)) throw std::runtime_error("Audio file does not exist");
    if (maxDurationSeconds <= 0.0) throw std::runtime_error("Maximum duration must be positive");
    if (identityIndex > 2) throw std::runtime_error("Diffusion identity must be 0, 1, or 2");
    if (!output.parent_path().empty()) fs::create_directories(output.parent_path());

    check(nva2x::SetCudaDeviceIfNeeded(0), "Select CUDA device");
    const auto samples = loadAudio(audio);
    const double durationSeconds = static_cast<double>(samples.size()) / kSampleRate;
    if (durationSeconds > maxDurationSeconds + 0.05) {
      throw std::runtime_error("Audio is " + std::to_string(durationSeconds) +
                               " seconds; configured maximum is " +
                               std::to_string(maxDurationSeconds) + " seconds");
    }
    std::cout << "Loaded " << samples.size() << " mono samples at " << kSampleRate << " Hz\n";
    const auto frames = infer(model, samples, modelType, identityIndex);
    writeJson(output, audio, frames);
    std::cout << "Wrote " << frames.size() << " frames and " << kArkitChannels.size()
              << " channels to " << pathUtf8(output) << "\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Error: " << error.what() << '\n';
    return 1;
  }
}
