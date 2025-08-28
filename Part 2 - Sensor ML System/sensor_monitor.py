from flask import Flask, jsonify, request
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta
import threading
import time
import schedule
from ml_pipeline import MLPipeline
import requests

app = Flask(__name__)
ml_pipeline = MLPipeline()

SENSOR_DATA_PATH = "/app/sensor-data"
MODELS_PATH = "/app/models"
SHARED_DATA_PATH = "/app/shared-data"

# Ensure directories exist
os.makedirs(SENSOR_DATA_PATH, exist_ok=True)
os.makedirs(MODELS_PATH, exist_ok=True)
os.makedirs(SHARED_DATA_PATH, exist_ok=True)

# Oil parameter thresholds
TEMPERATURE_THRESHOLD = 85.0  # Celsius
PRESSURE_THRESHOLD = 150.0    # PSI
VISCOSITY_THRESHOLD = 50.0    # cSt

class SensorDataGenerator:
    """Simulate sensor data generation"""
    
    def __init__(self):
        self.running = True
    
    def generate_sensor_reading(self):
        """Generate realistic oil parameter data"""
        base_temp = 75 + np.random.normal(0, 5)  # Base temperature around 75°C
        base_pressure = 120 + np.random.normal(0, 10)  # Base pressure around 120 PSI
        base_viscosity = 35 + np.random.normal(0, 3)  # Base viscosity around 35 cSt
        
        # Add some correlation between parameters
        if base_temp > 80:
            base_viscosity *= 0.95  # Higher temp reduces viscosity
            base_pressure *= 1.05   # Higher temp increases pressure
        
        # Occasionally generate threshold violations
        if np.random.random() < 0.1:  # 10% chance of threshold violation
            if np.random.random() < 0.33:
                base_temp += np.random.uniform(15, 25)  # Temperature spike
            elif np.random.random() < 0.5:
                base_pressure += np.random.uniform(30, 50)  # Pressure spike
            else:
                base_viscosity += np.random.uniform(20, 30)  # Viscosity spike
        
        return {
            'timestamp': datetime.now().isoformat(),
            'sensor_id': f"OIL_SENSOR_{np.random.randint(1, 6)}",
            'temperature': round(base_temp, 2),
            'pressure': round(base_pressure, 2),
            'viscosity': round(base_viscosity, 2),
            'flow_rate': round(45 + np.random.normal(0, 5), 2),
            'contamination_level': round(np.random.uniform(0.1, 5.0), 2)
        }
    
    def save_sensor_data(self, data):
        """Save sensor data to daily file"""
        today = datetime.now().strftime('%Y-%m-%d')
        filename = os.path.join(SENSOR_DATA_PATH, f"sensor_data_{today}.json")
        
        # Read existing data or create new list
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                existing_data = json.load(f)
        else:
            existing_data = []
        
        existing_data.append(data)
        
        with open(filename, 'w') as f:
            json.dump(existing_data, f, indent=2)
        
        return filename
    
    def run_data_generation(self):
        """Continuously generate sensor data"""
        while self.running:
            try:
                data = self.generate_sensor_reading()
                filename = self.save_sensor_data(data)
                
                # Check for threshold violations
                self.check_thresholds(data)
                
                # Trigger ML pipeline every 10 readings
                if len(self.get_today_readings()) % 10 == 0:
                    self.trigger_ml_pipeline()
                
                time.sleep(30)  # Generate data every 30 seconds
                
            except Exception as e:
                print(f"Error in data generation: {e}")
                time.sleep(30)
    
    def get_today_readings(self):
        """Get today's sensor readings"""
        today = datetime.now().strftime('%Y-%m-%d')
        filename = os.path.join(SENSOR_DATA_PATH, f"sensor_data_{today}.json")
        
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                return json.load(f)
        return []
    
    def check_thresholds(self, data):
        """Check if sensor data exceeds thresholds"""
        threshold_violations = []
        
        if data['temperature'] > TEMPERATURE_THRESHOLD:
            threshold_violations.append(f"Temperature: {data['temperature']}°C (> {TEMPERATURE_THRESHOLD}°C)")
        
        if data['pressure'] > PRESSURE_THRESHOLD:
            threshold_violations.append(f"Pressure: {data['pressure']} PSI (> {PRESSURE_THRESHOLD} PSI)")
        
        if data['viscosity'] > VISCOSITY_THRESHOLD:
            threshold_violations.append(f"Viscosity: {data['viscosity']} cSt (> {VISCOSITY_THRESHOLD} cSt)")
        
        if threshold_violations:
            alert_data = {
                'timestamp': data['timestamp'],
                'sensor_id': data['sensor_id'],
                'violations': threshold_violations,
                'all_parameters': data
            }
            
            self.notify_robots_threshold_violation(alert_data)
            self.save_alert(alert_data)
    
    def notify_robots_threshold_violation(self, alert_data):
        """Notify robot system of threshold violations"""
        try:
            robot_url = os.getenv('ROBOT_SYSTEM_URL', 'http://18.143.157.100:5003')
            response = requests.post(
                f'{robot_url}/threshold_alert',
                json=alert_data,
                timeout=5
            )
            print(f"Notified robots of threshold violation: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to notify robots: {e}")
    
    def save_alert(self, alert_data):
        """Save alert to shared data"""
        alert_file = os.path.join(SHARED_DATA_PATH, f"alert_{datetime.now().timestamp()}.json")
        with open(alert_file, 'w') as f:
            json.dump(alert_data, f, indent=2)
    
    def trigger_ml_pipeline(self):
        """Trigger ML pipeline to retrain model"""
        try:
            print("Triggering ML pipeline...")
            ml_pipeline.train_model()
            
            # Create trigger file for Jenkins
            trigger_file = os.path.join(SHARED_DATA_PATH, f"trigger_sensor-ml-pipeline_{datetime.now().timestamp()}.txt")
            with open(trigger_file, 'w') as f:
                f.write(f"ML Pipeline triggered at {datetime.now().isoformat()}")
                
        except Exception as e:
            print(f"Error triggering ML pipeline: {e}")

# Initialize sensor data generator
sensor_generator = SensorDataGenerator()

@app.route('/')
def index():
    return jsonify({
        'service': 'Sensor ML Pipeline',
        'status': 'running',
        'endpoints': [
            '/sensor_data - Get latest sensor data',
            '/model_info - Get current model information',
            '/train_model - Manually trigger model training',
            '/health - Health check'
        ]
    })

@app.route('/sensor_data')
def get_sensor_data():
    """Get latest sensor data"""
    try:
        readings = sensor_generator.get_today_readings()
        if readings:
            latest_reading = readings[-1]
            return jsonify({
                'latest_reading': latest_reading,
                'total_readings_today': len(readings),
                'thresholds': {
                    'temperature': TEMPERATURE_THRESHOLD,
                    'pressure': PRESSURE_THRESHOLD,
                    'viscosity': VISCOSITY_THRESHOLD
                }
            })
        else:
            return jsonify({
                'message': 'No sensor data available',
                'total_readings_today': 0
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/model_info')
def get_model_info():
    """Get current ML model information"""
    try:
        model_info = ml_pipeline.get_model_info()
        return jsonify(model_info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/train_model', methods=['POST'])
def train_model():
    """Manually trigger model training"""
    try:
        result = ml_pipeline.train_model()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'service': 'sensor-ml-system'})

def run_sensor_generation():
    """Run sensor data generation in background"""
    sensor_generator.run_data_generation()

if __name__ == '__main__':
    # Start sensor data generation in background thread
    sensor_thread = threading.Thread(target=run_sensor_generation, daemon=True)
    sensor_thread.start()
    
    app.run(host='0.0.0.0', port=5000, debug=True)