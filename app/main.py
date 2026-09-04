from flask import Flask, request, jsonify, render_template
from groq import Groq
import os, logging
from datetime import datetime
 
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
 
client = Groq(api_key=os.environ.get('GROQ_API_KEY'))
 
SYSTEM_PROMPT = '''You are InfraGPT, an expert DevOps and AWS engineer assistant.
You help with: AWS (EC2, EKS, S3, IAM, VPC, Lambda, CloudWatch),
Docker, Kubernetes, Terraform, Jenkins, CI/CD, Prometheus, Grafana.
Always structure your answers:
1. Direct answer first
2. Code or commands in code blocks
3. Best practice tip at end
Use markdown formatting. Be concise but complete.'''
 
@app.route('/')
def index():
    return render_template('index.html')
 
@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        msg = data.get('message', '').strip()
        if not msg:
            return jsonify({'error': 'Empty message'}), 400
        logger.info(f'[{datetime.now()}] Q: {msg[:60]}')
        response = client.chat.completions.create(
            model='llama3-70b-8192',
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user',   'content': msg}
            ],
            max_tokens=1024,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        logger.info(f'Reply sent ({len(reply)} chars)')
        return jsonify({'reply': reply})
    except Exception as e:
        logger.error(f'Error: {e}')
        return jsonify({'error': str(e)}), 500
 
@app.route('/health')
def health():
    return jsonify({
        'status':    'healthy',
        'service':   'InfraGPT',
        'timestamp': datetime.now().isoformat()
    }), 200
 
@app.route('/metrics')
def metrics():
    return '# HELP infragpt_up Service status\ninfragpt_up 1\n', \
        200, {'Content-Type': 'text/plain'}
 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
