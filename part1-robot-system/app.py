from flask import Flask, render_template, request, jsonify
import cv2
import face_recognition
import os
import json
from datetime import datetime, timedelta
import base64
import numpy as np
from database import DatabaseManager
from face_verification import FaceVerification
import requests

app = Flask(__name__)
db_manager = DatabaseManager()
face_verifier = FaceVerification()

SHARED_DATA_PATH = "/app/shared-data"
VISITOR_IMAGES_PATH = "/app/visitor-images"

# Ensure directories exist
os.makedirs(SHARED_DATA_PATH, exist_ok=True)
os.makedirs(VISITOR_IMAGES_PATH, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/verify_visitor', methods=['POST'])
def verify_visitor():
    try:
        data = request.get_json()
        
        # Extract visitor information
        visitor_name = data.get('visitor_name')
        destination_floor = data.get('destination_floor')
        purpose = data.get('purpose')
        duration_hours = int(data.get('duration_hours', 1))
        face_image_data = data.get('face_image')
        
        # Decode base64 image
        image_data = base64.b64decode(face_image_data.split(',')[1])
        nparr = np.frombuffer(image_data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Verify face
        face_encodings = face_recognition.face_encodings(image)
        
        if not face_encodings:
            return jsonify({
                'success': False,
                'message': 'No face detected in the image'
            })
        
        # Create visitor record
        visitor_id = db_manager.create_visitor_record(
            visitor_name, destination_floor, purpose, duration_hours
        )
        
        # Save visitor image with timestamp
        today_folder = datetime.now().strftime('%Y-%m-%d')
        daily_folder = os.path.join(VISITOR_IMAGES_PATH, today_folder)
        os.makedirs(daily_folder, exist_ok=True)
        
        image_filename = f"visitor_{visitor_id}_{datetime.now().strftime('%H%M%S')}.jpg"
        image_path = os.path.join(daily_folder, image_filename)
        cv2.imwrite(image_path, image)
        
        # Update visitor record with image path
        db_manager.update_visitor_image(visitor_id, image_path)
        
        # Create shared data for robots
        visitor_data = {
            'visitor_id': visitor_id,
            'name': visitor_name,
            'destination_floor': destination_floor,
            'purpose': purpose,
            'entry_time': datetime.now().isoformat(),
            'valid_until': (datetime.now() + timedelta(hours=duration_hours)).isoformat(),
            'image_path': image_path,
            'status': 'approved'
        }
        
        # Save to shared data directory
        shared_file = os.path.join(SHARED_DATA_PATH, f"visitor_{visitor_id}.json")
        with open(shared_file, 'w') as f:
            json.dump(visitor_data, f)
        
        # Notify robot system
        try:
            robot_response = requests.post(
                'http://robot-system:5000/new_visitor',
                json=visitor_data,
                timeout=5
            )
        except requests.exceptions.RequestException:
            pass  # Robot system might not be available
        
        # Trigger Jenkins pipeline
        trigger_jenkins_pipeline('verification-pipeline')
        
        return jsonify({
            'success': True,
            'visitor_id': visitor_id,
            'message': f'Access granted to floor {destination_floor} for {duration_hours} hours',
            'valid_until': visitor_data['valid_until']
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Verification failed: {str(e)}'
        })

def trigger_jenkins_pipeline(pipeline_name):
    """Trigger Jenkins pipeline"""
    try:
        jenkins_url = "http://jenkins:8080"
        # In real implementation, you would use Jenkins API with authentication
        # For demo purposes, we'll create a trigger file
        trigger_file = os.path.join(SHARED_DATA_PATH, f"trigger_{pipeline_name}_{datetime.now().timestamp()}.txt")
        with open(trigger_file, 'w') as f:
            f.write(f"Pipeline triggered at {datetime.now().isoformat()}")
    except Exception as e:
        print(f"Failed to trigger Jenkins pipeline: {e}")

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'service': 'verification-system'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
