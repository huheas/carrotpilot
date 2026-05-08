#pragma clang diagnostic ignored "-Wdeprecated-declarations"

#include "system/loggerd/encoder/ffmpeg_encoder.h"

#include <fcntl.h>
#include <unistd.h>

#include <cassert>
#include <cstdio>
#include <cstdlib>

#define __STDC_CONSTANT_MACROS

#include "third_party/libyuv/include/libyuv.h"

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/imgutils.h>
#include <libavutil/opt.h>
}

#include "common/swaglog.h"
#include "common/util.h"

const int env_debug_encoder = (getenv("DEBUG_ENCODER") != NULL) ? atoi(getenv("DEBUG_ENCODER")) : 0;

// Check if hardware acceleration is enabled, default to hardware encoding with fallback to software
const bool env_use_hardware_encoding = (getenv("USE_HARDWARE_ENCODING") != NULL) ? atoi(getenv("USE_HARDWARE_ENCODING")) : 1;

FfmpegEncoder::FfmpegEncoder(const EncoderInfo &encoder_info, int in_width, int in_height)
    : VideoEncoder(encoder_info, in_width, in_height) {
  frame = av_frame_alloc();
  assert(frame);
  frame->format = AV_PIX_FMT_YUV420P;
  frame->width = out_width;
  frame->height = out_height;
  frame->linesize[0] = out_width;
  frame->linesize[1] = out_width/2;
  frame->linesize[2] = out_width/2;

  convert_buf.resize(in_width * in_height * 3 / 2);

  if (in_width != out_width || in_height != out_height) {
    downscale_buf.resize(out_width * out_height * 3 / 2);
  }
}

FfmpegEncoder::~FfmpegEncoder() {
  encoder_close();
  av_frame_free(&frame);
}

void FfmpegEncoder::encoder_open() {
  auto codec_id = encoder_info.encode_type == cereal::EncodeIndex::Type::QCAMERA_H264
                      ? AV_CODEC_ID_H264
                      : encoder_info.encode_type == cereal::EncodeIndex::Type::FULL_H_E_V_C
                      ? AV_CODEC_ID_HEVC
                      : AV_CODEC_ID_FFVHUFF;

  // Check if hardware acceleration is enabled
  bool use_hardware = env_use_hardware_encoding && (codec_id == AV_CODEC_ID_H264 || codec_id == AV_CODEC_ID_HEVC);

  const AVCodec *codec = nullptr;
  if (use_hardware) {
    // Try to find hardware encoder first
    const char* hw_encoder_name = nullptr;
    if (codec_id == AV_CODEC_ID_H264) {
      hw_encoder_name = "h264_vaapi";
    } else if (codec_id == AV_CODEC_ID_HEVC) {
      hw_encoder_name = "hevc_vaapi";
    }

    if (hw_encoder_name) {
      codec = avcodec_find_encoder_by_name(hw_encoder_name);
      if (codec) {
        LOG("Using hardware encoder: %s", hw_encoder_name);
      } else {
        LOGW("Hardware encoder %s not found, falling back to software", hw_encoder_name);
        codec = avcodec_find_encoder(codec_id);
        use_hardware = false;
      }
    }
  } else {
    codec = avcodec_find_encoder(codec_id);
  }

  // For hardware acceleration, we need to set up hardware contexts BEFORE allocating the codec context
  AVCodecContext *temp_codec_ctx = NULL;
  if (use_hardware) {
    // Create hardware device context first
    AVBufferRef *hw_device_ctx = NULL;
    int err = av_hwdevice_ctx_create(&hw_device_ctx, AV_HWDEVICE_TYPE_VAAPI, "/dev/dri/renderD128", NULL, 0);
    if (err < 0) {
      LOGW("Failed to create VAAPI device context, falling back to software encoding: %d", err);
      use_hardware = false;
    } else {
      // Create hardware frames context
      AVBufferRef *hw_frames_ctx = NULL;
      AVHWFramesContext *frames_ctx = NULL;
      
      hw_frames_ctx = av_hwframe_ctx_alloc(hw_device_ctx);
      if (!hw_frames_ctx) {
        LOGW("Failed to allocate VAAPI frames context, falling back to software encoding");
        av_buffer_unref(&hw_device_ctx);
        use_hardware = false;
      } else {
        frames_ctx = (AVHWFramesContext*)(hw_frames_ctx->data);
        frames_ctx->format = AV_PIX_FMT_VAAPI;
        frames_ctx->sw_format = AV_PIX_FMT_NV12; // Use NV12 as source format since input is NV12
        frames_ctx->width = frame->width;
        frames_ctx->height = frame->height;
        frames_ctx->initial_pool_size = 20;
        
        err = av_hwframe_ctx_init(hw_frames_ctx);
        if (err < 0) {
          LOGW("Failed to initialize VAAPI frames context, falling back to software encoding: %d", err);
          av_buffer_unref(&hw_frames_ctx);
          av_buffer_unref(&hw_device_ctx);
          use_hardware = false;
        } else {
          // Now create the codec context with hardware setup
          temp_codec_ctx = avcodec_alloc_context3(codec);
          if (!temp_codec_ctx) {
            LOGE("Failed to allocate hardware codec context");
            av_buffer_unref(&hw_frames_ctx);
            av_buffer_unref(&hw_device_ctx);
            use_hardware = false;
          } else {
            temp_codec_ctx->width = frame->width;
            temp_codec_ctx->height = frame->height;
            temp_codec_ctx->pix_fmt = AV_PIX_FMT_VAAPI;
            temp_codec_ctx->time_base = (AVRational){ 1, encoder_info.fps };
            
            // Assign the hardware device and frames context to the codec context
            temp_codec_ctx->hw_device_ctx = av_buffer_ref(hw_device_ctx);
            temp_codec_ctx->hw_frames_ctx = av_buffer_ref(hw_frames_ctx);
            
            // Additional hardware-specific options for VAAPI encoder
            av_opt_set(temp_codec_ctx->priv_data, "compression_level", "1", 0); // Better performance
            av_opt_set(temp_codec_ctx->priv_data, "max_frame_size", "0", 0); // No max frame size
            av_opt_set(temp_codec_ctx->priv_data, "quality", "25", 0); // Quality level for HEVC
            av_opt_set(temp_codec_ctx->priv_data, "low_power", "1", 0); // Enable low power mode for better performance
            temp_codec_ctx->bit_rate = encoder_info.bitrate; // Use the specified bitrate
            // Set low latency options to reduce queue buildup
            temp_codec_ctx->rc_buffer_size = 1000000; // Reduce buffer size
            temp_codec_ctx->rc_initial_buffer_occupancy = 500000; // Reduce initial occupancy
            temp_codec_ctx->gop_size = 10; // Smaller GOP for better real-time performance
            temp_codec_ctx->max_b_frames = 0; // Set B frames to 0 to avoid lookahead depth issues
            
            // Open the hardware encoder
            err = avcodec_open2(temp_codec_ctx, codec, NULL);
            if (err < 0) {
              LOGW("Failed to open VAAPI hardware encoder, falling back to software: %d", err);
              avcodec_free_context(&temp_codec_ctx);
              av_buffer_unref(&hw_frames_ctx);
              av_buffer_unref(&hw_device_ctx);
              use_hardware = false;
            } else {
              LOG("Successfully initialized VAAPI hardware encoder");
              // Hardware encoder successfully initialized, assign to member variable
              this->codec_ctx = temp_codec_ctx;
              // Clean up local references, codec context keeps its own references
              av_buffer_unref(&hw_frames_ctx);
              av_buffer_unref(&hw_device_ctx);
              // Hardware encoder successfully initialized
            }
          }
        }
      }
    }
  }
  
  // If hardware encoding failed or was not used, initialize software encoding
  if (!use_hardware) {
    // Use software encoder
    this->codec_ctx = avcodec_alloc_context3(avcodec_find_encoder(codec_id));
    if (!this->codec_ctx) {
      LOGE("Failed to allocate software codec context");
    } else {
      this->codec_ctx->width = frame->width;
      this->codec_ctx->height = frame->height;
      this->codec_ctx->pix_fmt = AV_PIX_FMT_YUV420P;
      this->codec_ctx->time_base = (AVRational){ 1, encoder_info.fps };
      
      // Set additional options for HEVC encoder to reduce EAGAIN errors and optimize for real-time playback
      if (codec_id == AV_CODEC_ID_HEVC) {
        // Apply options only if they are supported by the encoder
        int ret = av_opt_set(this->codec_ctx->priv_data, "preset", "ultrafast", 0);
        if (ret < 0) {
          // If preset is not supported, continue without it
        }
        ret = av_opt_set(this->codec_ctx->priv_data, "tune", "zerolatency", 0);
        if (ret < 0) {
          // If tune is not supported, continue without it
        }
        // Set x265-specific options to avoid lookahead depth errors
        av_opt_set(this->codec_ctx->priv_data, "x265-params", "bframes=0", 0); // Use 0 B frames to avoid lookahead depth issues
        this->codec_ctx->gop_size = 10; // Smaller GOP for better real-time performance
        this->codec_ctx->max_b_frames = 0; // Set B frames to 0 to avoid lookahead depth issues
        this->codec_ctx->bit_rate = encoder_info.bitrate; // Use the specified bitrate
        // Set low latency options to reduce queue buildup
        this->codec_ctx->rc_buffer_size = 1000000; // Reduce buffer size
        this->codec_ctx->rc_initial_buffer_occupancy = 500000; // Reduce initial occupancy
      }
      
      int err = avcodec_open2(this->codec_ctx, avcodec_find_encoder(codec_id), NULL);
      if (err < 0) {
        LOGE("Failed to open software encoder: %d", err);
        avcodec_free_context(&this->codec_ctx);
      } else {
        LOG("Using software encoder");
      }
    }
  }

  this->codec_ctx->time_base = (AVRational){ 1, encoder_info.fps };

  is_open = true;
  segment_num++;
  counter = 0;
}

void FfmpegEncoder::encoder_close() {
  if (!is_open) return;

  avcodec_free_context(&codec_ctx);
  is_open = false;
}

int FfmpegEncoder::encode_frame(VisionBuf* buf, VisionIpcBufExtra *extra) {
  assert(buf->width == this->in_width);
  assert(buf->height == this->in_height);

  // Check if we're using hardware acceleration
  bool use_hardware = (this->codec_ctx->pix_fmt == AV_PIX_FMT_VAAPI);
  
  // If we've already switched to software encoding mode permanently, don't try hardware again
  if (this->software_encoding_mode) {
    use_hardware = false;
  }

  if (use_hardware) {
    // For hardware encoding, we need to properly handle frame format conversion
    // This is a simplified implementation that will be enhanced for full hardware acceleration

    // First, convert NV12 to I420 as before
    uint8_t *cy = convert_buf.data();
    uint8_t *cu = cy + in_width * in_height;
    uint8_t *cv = cu + (in_width / 2) * (in_height / 2);
    libyuv::NV12ToI420(buf->y, buf->stride,
                       buf->uv, buf->stride,
                       cy, in_width,
                       cu, in_width/2,
                       cv, in_width/2,
                       in_width, in_height);

    if (downscale_buf.size() > 0) {
      uint8_t *out_y = downscale_buf.data();
      uint8_t *out_u = out_y + frame->width * frame->height;
      uint8_t *out_v = out_u + (frame->width / 2) * (frame->height / 2);
      libyuv::I420Scale(cy, in_width,
                        cu, in_width/2,
                        cv, in_width/2,
                        in_width, in_height,
                        out_y, frame->width,
                        out_u, frame->width/2,
                        out_v, frame->width/2,
                        frame->width, frame->height,
                        libyuv::kFilterNone);

      // For VAAPI, we need to upload the frame to GPU
      // Create a temporary frame for the GPU upload
      AVFrame *hw_frame = av_frame_alloc();
      if (hw_frame) {
        // Set the hardware frames context properly
        if (this->codec_ctx->hw_frames_ctx) {
          // Reference the hardware frames context
          hw_frame->hw_frames_ctx = av_buffer_ref(this->codec_ctx->hw_frames_ctx);
        }
        
        hw_frame->format = AV_PIX_FMT_VAAPI;
        hw_frame->width = frame->width;
        hw_frame->height = frame->height;

        int err = av_hwframe_get_buffer(this->codec_ctx->hw_frames_ctx, hw_frame, 0);
        if (err >= 0) {
          // Map the frame to GPU memory
          AVFrame *sw_frame = av_frame_alloc();
          if (sw_frame) {
            sw_frame->format = AV_PIX_FMT_YUV420P;
            sw_frame->width = frame->width;
            sw_frame->height = frame->height;
            sw_frame->data[0] = out_y;
            sw_frame->data[1] = out_u;
            sw_frame->data[2] = out_v;
            sw_frame->linesize[0] = frame->width;
            sw_frame->linesize[1] = frame->width/2;
            sw_frame->linesize[2] = frame->width/2;

            // Upload to GPU
            err = av_hwframe_transfer_data(hw_frame, sw_frame, 0);
            if (err >= 0) {
              // Send the hardware frame for encoding
              err = avcodec_send_frame(this->codec_ctx, hw_frame);
            }
            av_frame_free(&sw_frame);
          } else {
            err = -1;
          }
        }
        
        // Clean up hardware frame reference
        if (hw_frame->hw_frames_ctx) {
          av_buffer_unref(&hw_frame->hw_frames_ctx);
        }

        if (err >= 0) {
          // Process received packets
          int ret = counter;
          AVPacket pkt;
          av_init_packet(&pkt);
          pkt.data = NULL;
          pkt.size = 0;
          while (ret >= 0) {
            err = avcodec_receive_packet(this->codec_ctx, &pkt);
            if (err == AVERROR_EOF) {
              break;
            } else if (err == AVERROR(EAGAIN)) {
              ret = 0;
              break;
            } else if (err < 0) {
              LOGE("avcodec_receive_packet error %d", err);
              if (err == AVERROR(EINVAL)) {
                LOGW("Encoder invalid argument error, continuing...");
                ret = 0;
                break;
              } else {
                ret = -1;
                break;
              }
            }

            if (env_debug_encoder) {
              printf("%20s got %8d bytes flags %8x idx %4d id %8d\n", encoder_info.publish_name, pkt.size, pkt.flags, counter, extra->frame_id);
            }

            publisher_publish(segment_num, counter, *extra,
              (pkt.flags & AV_PKT_FLAG_KEY) ? V4L2_BUF_FLAG_KEYFRAME : 0,
              kj::arrayPtr<capnp::byte>(pkt.data, (size_t)0), // TODO: get the header
              kj::arrayPtr<capnp::byte>(pkt.data, pkt.size));

            counter++;
          }
          av_packet_unref(&pkt);
          av_frame_free(&hw_frame);
          return ret;
        } else {
          LOGW("Hardware frame transfer failed, falling back to software encoding: %d", err);
          av_frame_free(&hw_frame);
          
          // IMPORTANT: After hardware failure, we should not continue to software path in the same function
          // to avoid the DPB (Decoded Picture Buffer) size issue
          // Instead, we should switch the encoder to software mode permanently for this instance
          LOG("Switching to software encoding mode for this encoder instance");
          
          // Close current hardware encoder context
          avcodec_free_context(&this->codec_ctx);
          
          // Initialize software encoder
          auto codec_id = encoder_info.encode_type == cereal::EncodeIndex::Type::QCAMERA_H264
                              ? AV_CODEC_ID_H264
                              : encoder_info.encode_type == cereal::EncodeIndex::Type::FULL_H_E_V_C
                              ? AV_CODEC_ID_HEVC
                              : AV_CODEC_ID_FFVHUFF;
          
          const AVCodec *codec = avcodec_find_encoder(codec_id);
          this->codec_ctx = avcodec_alloc_context3(codec);
          assert(this->codec_ctx);
          this->codec_ctx->width = frame->width;
          this->codec_ctx->height = frame->height;
          this->codec_ctx->pix_fmt = AV_PIX_FMT_YUV420P;
          this->codec_ctx->time_base = (AVRational){ 1, encoder_info.fps };
          
          // Set additional options for HEVC encoder to reduce EAGAIN errors and optimize for real-time playback
          if (codec_id == AV_CODEC_ID_HEVC) {
            // Apply options only if they are supported by the encoder
            int ret = av_opt_set(this->codec_ctx->priv_data, "preset", "ultrafast", 0);
            if (ret < 0) {
              // If preset is not supported, continue without it
            }
            ret = av_opt_set(this->codec_ctx->priv_data, "tune", "zerolatency", 0);
            if (ret < 0) {
              // If tune is not supported, continue without it
            }
            // Set x265-specific options to avoid lookahead depth errors
            av_opt_set(this->codec_ctx->priv_data, "x265-params", "bframes=0", 0); // Use 0 B frames to avoid lookahead depth issues
            this->codec_ctx->gop_size = 10; // Smaller GOP for better real-time performance
            this->codec_ctx->max_b_frames = 0; // Set B frames to 0 to avoid lookahead depth issues
            this->codec_ctx->bit_rate = encoder_info.bitrate; // Use the specified bitrate
            // Set low latency options to reduce queue buildup
            this->codec_ctx->rc_buffer_size = 1000000; // Reduce buffer size
            this->codec_ctx->rc_initial_buffer_occupancy = 500000; // Reduce initial occupancy
          }
          
          int sw_err = avcodec_open2(this->codec_ctx, codec, NULL);
          assert(sw_err >= 0);
          LOG("Successfully switched to software encoding");
          this->software_encoding_mode = true;
        }
        // After switching to software encoding, we need to return to avoid the DPB size issue
        // The frame will be encoded in the next call using the new software encoder context
        return -1; // Return error to indicate this frame needs to be retried with software encoder
      } else {
        LOGW("Failed to allocate hardware frame, falling back to software encoding");
        
        // Also switch to software mode permanently
        avcodec_free_context(&this->codec_ctx);
        
        auto codec_id = encoder_info.encode_type == cereal::EncodeIndex::Type::QCAMERA_H264
                            ? AV_CODEC_ID_H264
                            : encoder_info.encode_type == cereal::EncodeIndex::Type::FULL_H_E_V_C
                            ? AV_CODEC_ID_HEVC
                            : AV_CODEC_ID_FFVHUFF;
        
        const AVCodec *codec = avcodec_find_encoder(codec_id);
        this->codec_ctx = avcodec_alloc_context3(codec);
        assert(this->codec_ctx);
        this->codec_ctx->width = frame->width;
        this->codec_ctx->height = frame->height;
        this->codec_ctx->pix_fmt = AV_PIX_FMT_YUV420P;
        this->codec_ctx->time_base = (AVRational){ 1, encoder_info.fps };
        
        // Set additional options for HEVC encoder to reduce EAGAIN errors and optimize for real-time playback
        if (codec_id == AV_CODEC_ID_HEVC) {
          // Apply options only if they are supported by the encoder
          int ret = av_opt_set(this->codec_ctx->priv_data, "preset", "ultrafast", 0);
          if (ret < 0) {
            // If preset is not supported, continue without it
          }
          ret = av_opt_set(this->codec_ctx->priv_data, "tune", "zerolatency", 0);
          if (ret < 0) {
            // If tune is not supported, continue without it
          }
          // Set x265-specific options to avoid lookahead depth errors
          av_opt_set(this->codec_ctx->priv_data, "x265-params", "bframes=0", 0); // Use 0 B frames to avoid lookahead depth issues
          this->codec_ctx->gop_size = 10; // Smaller GOP for better real-time performance
          this->codec_ctx->max_b_frames = 0; // Set B frames to 0 to avoid lookahead depth issues
          this->codec_ctx->bit_rate = encoder_info.bitrate; // Use the specified bitrate
          // Set low latency options to reduce queue buildup
          this->codec_ctx->rc_buffer_size = 1000000; // Reduce buffer size
          this->codec_ctx->rc_initial_buffer_occupancy = 500000; // Reduce initial occupancy
        }
        
        int sw_err2 = avcodec_open2(this->codec_ctx, codec, NULL);
        assert(sw_err2 >= 0);
        LOG("Successfully switched to software encoding after hardware allocation failure");
        this->software_encoding_mode = true;
        
        // After switching to software encoding, we need to return to avoid the DPB size issue
        // The frame will be encoded in the next call using the new software encoder context
        return -1; // Return error to indicate this frame needs to be retried with software encoder
      }
    } else {
      // No downscaling needed - use original frame data directly
      // For VAAPI, we need to upload the frame to GPU
      // Create a temporary frame for the GPU upload
      AVFrame *hw_frame = av_frame_alloc();
      if (hw_frame) {
        // Set the hardware frames context properly
        if (this->codec_ctx->hw_frames_ctx) {
          // Reference the hardware frames context
          hw_frame->hw_frames_ctx = av_buffer_ref(this->codec_ctx->hw_frames_ctx);
        }
        
        hw_frame->format = AV_PIX_FMT_VAAPI;
        hw_frame->width = frame->width;
        hw_frame->height = frame->height;

        int err = av_hwframe_get_buffer(this->codec_ctx->hw_frames_ctx, hw_frame, 0);
        if (err >= 0) {
          // Map the frame to GPU memory
          AVFrame *sw_frame = av_frame_alloc();
          if (sw_frame) {
            sw_frame->format = AV_PIX_FMT_YUV420P;
            sw_frame->width = frame->width;
            sw_frame->height = frame->height;
            sw_frame->data[0] = cy;
            sw_frame->data[1] = cu;
            sw_frame->data[2] = cv;
            sw_frame->linesize[0] = frame->width;
            sw_frame->linesize[1] = frame->width/2;
            sw_frame->linesize[2] = frame->width/2;

            // Upload to GPU
            err = av_hwframe_transfer_data(hw_frame, sw_frame, 0);
            if (err >= 0) {
              // Send the hardware frame for encoding
              err = avcodec_send_frame(this->codec_ctx, hw_frame);
            }
            av_frame_free(&sw_frame);
          } else {
            err = -1;
          }
        }
        
        // Clean up hardware frame reference
        if (hw_frame->hw_frames_ctx) {
          av_buffer_unref(&hw_frame->hw_frames_ctx);
        }

        if (err >= 0) {
          // Process received packets
          int ret = counter;
          AVPacket pkt;
          av_init_packet(&pkt);
          pkt.data = NULL;
          pkt.size = 0;
          while (ret >= 0) {
            err = avcodec_receive_packet(this->codec_ctx, &pkt);
            if (err == AVERROR_EOF) {
              break;
            } else if (err == AVERROR(EAGAIN)) {
              ret = 0;
              break;
            } else if (err < 0) {
              LOGE("avcodec_receive_packet error %d", err);
              if (err == AVERROR(EINVAL)) {
                LOGW("Encoder invalid argument error, continuing...");
                ret = 0;
                break;
              } else {
                ret = -1;
                break;
              }
            }

            if (env_debug_encoder) {
              printf("%20s got %8d bytes flags %8x idx %4d id %8d\n", encoder_info.publish_name, pkt.size, pkt.flags, counter, extra->frame_id);
            }

            publisher_publish(segment_num, counter, *extra,
              (pkt.flags & AV_PKT_FLAG_KEY) ? V4L2_BUF_FLAG_KEYFRAME : 0,
              kj::arrayPtr<capnp::byte>(pkt.data, (size_t)0), // TODO: get the header
              kj::arrayPtr<capnp::byte>(pkt.data, pkt.size));

            counter++;
          }
          av_packet_unref(&pkt);
          av_frame_free(&hw_frame);
          return ret;
        } else {
          LOGW("Hardware frame transfer failed for non-scaled frame, falling back to software encoding: %d", err);
          av_frame_free(&hw_frame);
          
          // Switch to software mode permanently
          this->software_encoding_mode = true;
          
          // Close current hardware encoder context
          avcodec_free_context(&this->codec_ctx);
          
          // Initialize software encoder
          auto codec_id = encoder_info.encode_type == cereal::EncodeIndex::Type::QCAMERA_H264
                              ? AV_CODEC_ID_H264
                              : encoder_info.encode_type == cereal::EncodeIndex::Type::FULL_H_E_V_C
                              ? AV_CODEC_ID_HEVC
                              : AV_CODEC_ID_FFVHUFF;
          
          const AVCodec *codec = avcodec_find_encoder(codec_id);
          this->codec_ctx = avcodec_alloc_context3(codec);
          assert(this->codec_ctx);
          this->codec_ctx->width = frame->width;
          this->codec_ctx->height = frame->height;
          this->codec_ctx->pix_fmt = AV_PIX_FMT_YUV420P;
          this->codec_ctx->time_base = (AVRational){ 1, encoder_info.fps };
          
          // Set additional options for HEVC encoder to reduce EAGAIN errors and optimize for real-time playback
          if (codec_id == AV_CODEC_ID_HEVC) {
            // Apply options only if they are supported by the encoder
            int ret = av_opt_set(this->codec_ctx->priv_data, "preset", "ultrafast", 0);
            if (ret < 0) {
              // If preset is not supported, continue without it
            }
            ret = av_opt_set(this->codec_ctx->priv_data, "tune", "zerolatency", 0);
            if (ret < 0) {
              // If tune is not supported, continue without it
            }
            // Set x265-specific options to avoid lookahead depth errors
            av_opt_set(this->codec_ctx->priv_data, "x265-params", "bframes=0", 0); // Use 0 B frames to avoid lookahead depth issues
            this->codec_ctx->gop_size = 10; // Smaller GOP for better real-time performance
            this->codec_ctx->max_b_frames = 0; // Set B frames to 0 to avoid lookahead depth issues
            this->codec_ctx->bit_rate = encoder_info.bitrate; // Use the specified bitrate
            // Set low latency options to reduce queue buildup
            this->codec_ctx->rc_buffer_size = 1000000; // Reduce buffer size
            this->codec_ctx->rc_initial_buffer_occupancy = 500000; // Reduce initial occupancy
          }
          
          int sw_err = avcodec_open2(this->codec_ctx, codec, NULL);
          assert(sw_err >= 0);
          LOG("Successfully switched to software encoding after hardware failure");
          
          // Return error to indicate this frame needs to be retried with software encoder
          return -1;
        }
      } else {
        LOGE("Failed to allocate hardware frame for non-scaled path");
        
        // Switch to software mode permanently
        this->software_encoding_mode = true;
        
        // Close current hardware encoder context
        avcodec_free_context(&this->codec_ctx);
        
        // Initialize software encoder
        auto codec_id = encoder_info.encode_type == cereal::EncodeIndex::Type::QCAMERA_H264
                            ? AV_CODEC_ID_H264
                            : encoder_info.encode_type == cereal::EncodeIndex::Type::FULL_H_E_V_C
                            ? AV_CODEC_ID_HEVC
                            : AV_CODEC_ID_FFVHUFF;
        
        const AVCodec *codec = avcodec_find_encoder(codec_id);
        this->codec_ctx = avcodec_alloc_context3(codec);
        assert(this->codec_ctx);
        this->codec_ctx->width = frame->width;
        this->codec_ctx->height = frame->height;
        this->codec_ctx->pix_fmt = AV_PIX_FMT_YUV420P;
        this->codec_ctx->time_base = (AVRational){ 1, encoder_info.fps };
        
        // Set additional options for HEVC encoder to reduce EAGAIN errors and optimize for real-time playback
        if (codec_id == AV_CODEC_ID_HEVC) {
          // Apply options only if they are supported by the encoder
          int ret = av_opt_set(this->codec_ctx->priv_data, "preset", "ultrafast", 0);
          if (ret < 0) {
            // If preset is not supported, continue without it
          }
          ret = av_opt_set(this->codec_ctx->priv_data, "tune", "zerolatency", 0);
          if (ret < 0) {
            // If tune is not supported, continue without it
          }
          // Set x265-specific options to avoid lookahead depth errors
          av_opt_set(this->codec_ctx->priv_data, "x265-params", "bframes=0", 0); // Use 0 B frames to avoid lookahead depth issues
          this->codec_ctx->gop_size = 10; // Smaller GOP for better real-time performance
          this->codec_ctx->max_b_frames = 0; // Set B frames to 0 to avoid lookahead depth issues
          this->codec_ctx->bit_rate = encoder_info.bitrate; // Use the specified bitrate
          // Set low latency options to reduce queue buildup
          this->codec_ctx->rc_buffer_size = 1000000; // Reduce buffer size
          this->codec_ctx->rc_initial_buffer_occupancy = 500000; // Reduce initial occupancy
        }
        
        int sw_err = avcodec_open2(this->codec_ctx, codec, NULL);
        assert(sw_err >= 0);
        LOG("Successfully switched to software encoding after hardware allocation failure");
        
        // Return error to indicate this frame needs to be retried with software encoder
        return -1;
      }
    }
  } else {
    // This is the software encoding path when hardware is not used from the beginning
    uint8_t *cy = convert_buf.data();
    uint8_t *cu = cy + in_width * in_height;
    uint8_t *cv = cu + (in_width / 2) * (in_height / 2);
    libyuv::NV12ToI420(buf->y, buf->stride,
                       buf->uv, buf->stride,
                       cy, in_width,
                       cu, in_width/2,
                       cv, in_width/2,
                       in_width, in_height);

    if (downscale_buf.size() > 0) {
      uint8_t *out_y = downscale_buf.data();
      uint8_t *out_u = out_y + frame->width * frame->height;
      uint8_t *out_v = out_u + (frame->width / 2) * (frame->height / 2);
      libyuv::I420Scale(cy, in_width,
                        cu, in_width/2,
                        cv, in_width/2,
                        in_width, in_height,
                        out_y, frame->width,
                        out_u, frame->width/2,
                        out_v, frame->width/2,
                        frame->width, frame->height,
                        libyuv::kFilterNone);
      frame->data[0] = out_y;
      frame->data[1] = out_u;
      frame->data[2] = out_v;
    } else {
      frame->data[0] = cy;
      frame->data[1] = cu;
      frame->data[2] = cv;
    }
    frame->pts = counter*50*1000; // 50ms per frame

    int ret = counter;

    int err = avcodec_send_frame(this->codec_ctx, frame);
    if (err < 0) {
      LOGE("avcodec_send_frame error %d", err);
      ret = -1;
    }

    AVPacket pkt;
    av_init_packet(&pkt);
    pkt.data = NULL;
    pkt.size = 0;
    while (ret >= 0) {
      err = avcodec_receive_packet(this->codec_ctx, &pkt);
      if (err == AVERROR_EOF) {
        break;
      } else if (err == AVERROR(EAGAIN)) {
        // Encoder might need a few frames on startup to get started. Keep going
        ret = 0;
        break;
      } else if (err < 0) {
        LOGE("avcodec_receive_packet error %d", err);
        // Try to handle encoder errors gracefully instead of breaking completely
        if (err == AVERROR(EINVAL)) {
          // For invalid argument errors, try to reinitialize the encoder
          LOGW("Encoder invalid argument error, continuing...");
          ret = 0;
          break;
        } else {
          ret = -1;
          break;
        }
      }

      if (env_debug_encoder) {
        printf("%20s got %8d bytes flags %8x idx %4d id %8d\n", encoder_info.publish_name, pkt.size, pkt.flags, counter, extra->frame_id);
      }

      publisher_publish(segment_num, counter, *extra,
        (pkt.flags & AV_PKT_FLAG_KEY) ? V4L2_BUF_FLAG_KEYFRAME : 0,
        kj::arrayPtr<capnp::byte>(pkt.data, (size_t)0), // TODO: get the header
        kj::arrayPtr<capnp::byte>(pkt.data, pkt.size));

      counter++;
    }
    av_packet_unref(&pkt);
    return ret;
  }
  
  // This line should never be reached due to the if/else structure,
  // but added to satisfy compiler requirements
  return -1;
}
