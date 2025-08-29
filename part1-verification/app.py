from flask import Flask, render_template, request, jsonify
import cv2
import face_recognition
import os
import json
from datetime import datetime, timedelta
import base64
import numpy as np
from face_verification import FaceVerification
import requests

app = Flask(__name__)
face_verifier = FaceVerification()

SHARED_DATA_PATH = "/app/shared-data"
VISITOR_IMAGES_PATH = "/app/visitor-images"
VISITOR_RECORDS_PATH = "/app/visitor-records"

# Ensure directories exist
os.makedirs(SHARED_DATA_PATH, exist_ok=True)
os.makedirs(VISITOR_IMAGES_PATH, exist_ok=True)
os.makedirs(VISITOR_RECORDS_PATH, exist_ok=True)

def get_next_visitor_id():
    """Generate next visitor ID"""
    try:
        id_file = os.path.join(VISITOR_RECORDS_PATH, "next_id.txt")
        if os.path.exists(id_file):
            with open(id_file, 'r') as f:
                next_id = int(f.read().strip())
        else:
            next_id = 1
        
        # Update next ID
        with open(id_file, 'w') as f:
            f.write(str(next_id + 1))
        
        return next_id
    except Exception as e:
        print(f"Error generating visitor ID: {e}")
        return int(datetime.now().timestamp()) % 10000  # Fallback ID

def save_visitor_record(visitor_data):
    """Save visitor record to JSON file"""
    try:
        visitor_id = visitor_data['visitor_id']
        filename = os.path.join(VISITOR_RECORDS_PATH, f"visitor_{visitor_id}.json")
        
        with open(filename, 'w') as f:
            json.dump(visitor_data, f, indent=2)
        
        # Also maintain a daily log
        today = datetime.now().strftime('%Y-%m-%d')
        daily_log = os.path.join(VISITOR_RECORDS_PATH, f"daily_visitors_{today}.json")
        
        if os.path.exists(daily_log):
            with open(daily_log, 'r') as f:
                daily_visitors = json.load(f)
        else:
            daily_visitors = []
        
        daily_visitors.append(visitor_data)
        
        with open(daily_log, 'w') as f:
            json.dump(daily_visitors, f, indent=2)
        
        return True
    except Exception as e:
        print(f"Error saving visitor record: {e}")
        return False

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
        
        # Generate visitor ID
        visitor_id = get_next_visitor_id()
        
        # Save visitor image with timestamp
        today_folder = datetime.now().strftime('%Y-%m-%d')
        daily_folder = os.path.join(VISITOR_IMAGES_PATH, today_folder)
        os.makedirs(daily_folder, exist_ok=True)
        
        image_filename = f"visitor_{visitor_id}_{datetime.now().strftime('%H%M%S')}.jpg"
        image_path = os.path.join(daily_folder, image_filename)
        cv2.imwrite(image_path, image)
        
        # Create visitor record
        visitor_data = {
            'visitor_id': visitor_id,
            'name': visitor_name,
            'destination_floor': int(destination_floor),
            'purpose': purpose,
            'duration_hours': duration_hours,
            'entry_time': datetime.now().isoformat(),
            'valid_until': (datetime.now() + timedelta(hours=duration_hours)).isoformat(),
            'image_path': image_path,
            'status': 'approved'
        }
        
        # Save visitor record
        if not save_visitor_record(visitor_data):
            return jsonify({
                'success': False,
                'message': 'Failed to save visitor record'
            })
        
        # Save to shared data directory for Jenkins pipeline
        shared_file = os.path.join(SHARED_DATA_PATH, f"visitor_{visitor_id}.json")
        with open(shared_file, 'w') as f:
            json.dump(visitor_data, f, indent=2)
        
        # Notify robot system
        try:
            robot_url = os.getenv('ROBOT_SYSTEM_URL', 'http://robot-system:5000')
            robot_response = requests.post(
                f'{robot_url}/new_visitor',
                json=visitor_data,
                timeout=5
            )
            print(f"Notified robot system: {robot_response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to notify robot system: {e}")
        
        # Trigger Jenkins pipeline
        trigger_jenkins_pipeline('verification-pipeline')
        
        return jsonify({
            'success': True,
            'visitor_id': visitor_id,
            'message': f'Access granted to floor {destination_floor} for {duration_hours} hours',
            'valid_until': visitor_data['valid_until']
        })
        
    except Exception as e:
        print(f"Verification error: {e}")
        return jsonify({
            'success': False,
            'message': f'Verification failed: {str(e)}'
        })

@app.route('/get_visitors')
def get_visitors():
    """Get all visitors for today"""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        daily_log = os.path.join(VISITOR_RECORDS_PATH, f"daily_visitors_{today}.json")
        
        if os.path.exists(daily_log):
            with open(daily_log, 'r') as f:
                visitors = json.load(f)
        else:
            visitors = []
        
        return jsonify({
            'success': True,
            'visitors': visitors,
            'total': len(visitors),
            'date': today
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/get_visitor/<int:visitor_id>')
def get_visitor(visitor_id):
    """Get specific visitor by ID"""
    try:
        filename = os.path.join(VISITOR_RECORDS_PATH, f"visitor_{visitor_id}.json")
        
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                visitor_data = json.load(f)
            
            return jsonify({
                'success': True,
                'visitor': visitor_data
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Visitor not found'
            }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/stats')
def get_stats():
    """Get visitor statistics"""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        daily_log = os.path.join(VISITOR_RECORDS_PATH, f"daily_visitors_{today}.json")
        
        if os.path.exists(daily_log):
            with open(daily_log, 'r') as f:
                visitors = json.load(f)
        else:
            visitors = []
        
        # Calculate statistics
        stats = {
            'total_visitors_today': len(visitors),
            'visitors_by_floor': {},
            'visitors_by_purpose': {},
            'average_duration': 0
        }
        
        if visitors:
            # Group by floor
            for visitor in visitors:
                floor = visitor.get('destination_floor', 'Unknown')
                if floor in stats['visitors_by_floor']:
                    stats['visitors_by_floor'][floor] += 1
                else:
                    stats['visitors_by_floor'][floor] = 1
            
            # Group by purpose keywords
            for visitor in visitors:
                purpose = visitor.get('purpose', '').lower()
                if 'meeting' in purpose:
                    key = 'Meetings'
                elif 'maintenance' in purpose:
                    key = 'Maintenance'
                elif 'delivery' in purpose:
                    key = 'Delivery'
                else:
                    key = 'Other'
                
                if key in stats['visitors_by_purpose']:
                    stats['visitors_by_purpose'][key] += 1
                else:
                    stats['visitors_by_purpose'][key] = 1
            
            # Average duration
            total_duration = sum(v.get('duration_hours', 0) for v in visitors)
            stats['average_duration'] = round(total_duration / len(visitors), 2)
        
        return jsonify({
            'success': True,
            'stats': stats,
            'date': today
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

def trigger_jenkins_pipeline(pipeline_name):
    """Trigger Jenkins pipeline"""
    try:
        jenkins_url = os.getenv('JENKINS_URL', 'http://jenkins:8080')
        # Create trigger file for Jenkins to pick up
        trigger_file = os.path.join(SHARED_DATA_PATH, f"trigger_{pipeline_name}_{datetime.now().timestamp()}.txt")
        with open(trigger_file, 'w') as f:
            f.write(f"Pipeline triggered at {datetime.now().isoformat()}")
        print(f"Created trigger file: {trigger_file}")
    except Exception as e:
        print(f"Failed to trigger Jenkins pipeline: {e}")

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy', 
        'service': 'verification-system',
        'storage': 'file-based',
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
