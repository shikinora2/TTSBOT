#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gradio Demo for Valtec Vietnamese TTS
A simple web interface for text-to-speech synthesis.

Usage:
    python demo_gradio.py
    
    # Or with custom model
    python demo_gradio.py --checkpoint ./pretrained/G_100000.pth --config ./pretrained/config.json
"""

import os
import argparse
import tempfile
import torch
import gradio as gr
from pathlib import Path

from infer import VietnameseTTS, find_latest_checkpoint


def parse_args():
    parser = argparse.ArgumentParser(description="Gradio Demo for Vietnamese TTS")
    parser.add_argument("--checkpoint", "-c", type=str, default=None,
                        help="Path to generator checkpoint (G_*.pth)")
    parser.add_argument("--model_dir", type=str, default="./pretrained",
                        help="Model directory to find latest checkpoint")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to config.json")
    parser.add_argument("--device", type=str, default="cuda",
                        help="Device (cuda or cpu)")
    parser.add_argument("--port", type=int, default=7860,
                        help="Port to run the demo on")
    parser.add_argument("--share", action="store_true",
                        help="Create a public share link")
    return parser.parse_args()


class TTSInterface:
    """Wrapper for TTS model with Gradio interface."""
    
    def __init__(self, checkpoint_path, config_path, device="cuda"):
        print("Loading TTS model...")
        self.tts = VietnameseTTS(checkpoint_path, config_path, device)
        self.temp_dir = Path(tempfile.gettempdir()) / "valtec_tts_demo"
        self.temp_dir.mkdir(exist_ok=True)
        print("Model loaded successfully!")
    
    def synthesize(self, text, speaker, speed, noise_scale, noise_scale_w, sdp_ratio):
        """
        Synthesize speech from text with given parameters.
        
        Returns:
            tuple: (audio_file_path, success_message)
        """
        try:
            if not text or not text.strip():
                return None, "⚠️ Vui lòng nhập văn bản"
            
            # Synthesize
            audio, sr = self.tts.synthesize(
                text=text.strip(),
                speaker=speaker,
                length_scale=speed,
                noise_scale=noise_scale,
                noise_scale_w=noise_scale_w,
                sdp_ratio=sdp_ratio,
            )
            
            # Save to temp file
            output_path = self.temp_dir / f"output_{hash(text)}.wav"
            self.tts.save_audio(audio, sr, str(output_path))
            
            return str(output_path), f"✅ Tạo giọng nói thành công! ({len(audio)/sr:.2f}s)"
            
        except Exception as e:
            return None, f"❌ Lỗi: {str(e)}"


def create_demo(tts_interface):
    """Create Gradio interface."""
    
    # Example texts
    examples = [
        ["Xin chào, tôi là trợ lý AI của Valtec", "male", 1.0, 0.667, 0.8, 0.0],
        ["Buổi sáng hôm nay trời trong xanh và gió thổi rất nhẹ", "male", 1.0, 0.667, 0.8, 0.0],
        ["Tôi pha một tách cà phê nóng và ngồi nhìn ánh nắng chiếu qua cửa sổ", "female", 1.0, 0.667, 0.8, 0.0],
        ["Việt Nam là một đất nước xinh đẹp với văn hóa phong phú", "male", 0.9, 0.667, 0.8, 0.0],
        ["Công nghệ trí tuệ nhân tạo đang phát triển rất nhanh", "female", 1.1, 0.667, 0.8, 0.0],
    ]
    
    with gr.Blocks(
        theme=gr.themes.Soft(
            primary_hue="blue",
            secondary_hue="cyan",
        ),
        title="Valtec Vietnamese TTS",
        css="""
        .gradio-container {
            max-width: 900px !important;
        }
        #title {
            text-align: center;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: bold;
        }
        """
    ) as demo:
        
        # Header
        gr.Markdown(
            """
            # <span id="title">🎙️ Valtec Vietnamese TTS</span>
            
            ### Hệ thống chuyển văn bản thành giọng nói tiếng Việt
            
            Nhập văn bản tiếng Việt và chọn giọng đọc để tạo audio.
            """
        )
        
        with gr.Row():
            with gr.Column(scale=2):
                # Input text
                text_input = gr.Textbox(
                    label="📝 Văn bản đầu vào",
                    placeholder="Nhập văn bản tiếng Việt ở đây...",
                    lines=5,
                    max_lines=10,
                )
                
                # Speaker selection
                speaker_dropdown = gr.Dropdown(
                    choices=tts_interface.tts.speakers,
                    value=tts_interface.tts.speakers[0],
                    label="🎤 Chọn giọng đọc",
                    info="Chọn người đọc từ danh sách"
                )
                
                # Synthesis button
                synthesize_btn = gr.Button(
                    "🔊 Tạo giọng nói",
                    variant="primary",
                    size="lg"
                )
            
            with gr.Column(scale=1):
                # Advanced settings
                with gr.Accordion("⚙️ Cài đặt nâng cao", open=False):
                    speed_slider = gr.Slider(
                        minimum=0.5,
                        maximum=2.0,
                        value=1.0,
                        step=0.1,
                        label="Tốc độ",
                        info="< 1.0: Nhanh hơn | > 1.0: Chậm hơn"
                    )
                    
                    noise_scale_slider = gr.Slider(
                        minimum=0.1,
                        maximum=1.5,
                        value=0.667,
                        step=0.01,
                        label="Noise Scale",
                        info="Điều khiển độ biến thiên giọng nói"
                    )
                    
                    noise_scale_w_slider = gr.Slider(
                        minimum=0.1,
                        maximum=1.5,
                        value=0.8,
                        step=0.01,
                        label="Duration Noise",
                        info="Điều khiển độ biến thiên thời lượng"
                    )
                    
                    sdp_ratio_slider = gr.Slider(
                        minimum=0.0,
                        maximum=1.0,
                        value=0.0,
                        step=0.1,
                        label="SDP Ratio",
                        info="0: Xác định | 1: Ngẫu nhiên"
                    )
        
        # Output
        with gr.Row():
            with gr.Column():
                audio_output = gr.Audio(
                    label="🔊 Audio đầu ra",
                    type="filepath",
                    interactive=False
                )
                status_output = gr.Textbox(
                    label="📊 Trạng thái",
                    interactive=False,
                    show_label=False
                )
        
        # Examples
        gr.Markdown("### 📚 Ví dụ")
        gr.Examples(
            examples=examples,
            inputs=[
                text_input,
                speaker_dropdown,
                speed_slider,
                noise_scale_slider,
                noise_scale_w_slider,
                sdp_ratio_slider
            ],
            outputs=[audio_output, status_output],
            fn=tts_interface.synthesize,
            cache_examples=False,
        )
        
        # Event handlers
        synthesize_btn.click(
            fn=tts_interface.synthesize,
            inputs=[
                text_input,
                speaker_dropdown,
                speed_slider,
                noise_scale_slider,
                noise_scale_w_slider,
                sdp_ratio_slider,
            ],
            outputs=[audio_output, status_output],
        )
        
        # Footer
        gr.Markdown(
            """
            ---
            <div style="text-align: center; color: #666; font-size: 0.9em;">
                Powered by <b>Valtec TTS</b>
            </div>
            """
        )
    
    return demo


def main():
    args = parse_args()
    
    # Check device
    if args.device == "cuda" and not torch.cuda.is_available():
        print("⚠️ CUDA not available, using CPU")
        args.device = "cpu"
    
    # Find checkpoint
    checkpoint_path = args.checkpoint
    if checkpoint_path is None:
        checkpoint_path = find_latest_checkpoint(args.model_dir, "G")
        if checkpoint_path is None:
            print(f"❌ Error: No checkpoint found in {args.model_dir}")
            print("Please specify --checkpoint or --model_dir")
            return
        print(f"✅ Using checkpoint: {checkpoint_path}")
    
    # Find config
    config_path = args.config
    if config_path is None:
        config_dir = os.path.dirname(checkpoint_path)
        config_path = os.path.join(config_dir, "config.json")
        if not os.path.exists(config_path):
            print(f"❌ Error: config.json not found at {config_path}")
            return
        print(f"✅ Using config: {config_path}")
    
    # Create interface
    tts_interface = TTSInterface(checkpoint_path, config_path, args.device)
    demo = create_demo(tts_interface)
    
    # Launch
    print(f"\n🚀 Starting Gradio demo on port {args.port}...")
    demo.launch(
        server_name="0.0.0.0",
        server_port=args.port,
        share=args.share,
        show_error=True,
    )


if __name__ == "__main__":
    main()
