import os
import gradio as gr
from dawa import app as flask_app

with gr.Blocks(title="PharmaCare") as blocks:
    gr.HTML("""
    <div style="text-align:center; padding:40px;">
        <h1>💊 PharmaCare Pharmacy System</h1>
        <p>Loading pharmacy management system...</p>
        <iframe src="/" style="width:100%; height:80vh; border:none; border-radius:12px; margin-top:20px;"></iframe>
    </div>
    """)

app = gr.mount_gradio_app(flask_app, blocks, path="/gradio")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 7860))
    flask_app.run(host='0.0.0.0', port=port, debug=False)
