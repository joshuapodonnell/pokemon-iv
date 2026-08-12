import os
import tempfile
from PIL import Image
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config

MODEL_PATH = "mlx-community/Qwen2-VL-2B-Instruct-4bit"

print("1. Creating dummy image...")
img = Image.new('RGB', (400, 400), color='red')
with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
    img.save(tmp, format="PNG")
    tmp_path = tmp.name

try:
    print(f"2. Loading {MODEL_PATH}...")
    model, processor = load(MODEL_PATH)
    config = load_config(MODEL_PATH)
    print("   -> Model loaded successfully!")

    print("3. Formatting prompt...")
    prompt = "What color is this image?"
    formatted = apply_chat_template(processor, config, prompt, num_images=1)

    print("4. Running inference (this is where it usually segfaults)...")
    output = generate(
        model,
        processor,
        formatted,
        [tmp_path],
        verbose=True,
        max_tokens=50,
        temperature=0.0
    )
    print("\nSUCCESS! Output:", output.text.strip())
finally:
    os.unlink(tmp_path)
    print("Cleanup done.")