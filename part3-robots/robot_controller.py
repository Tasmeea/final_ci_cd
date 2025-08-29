from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import json
import os
import threading
import time
from datetime import datetime, timedelta
import numpy as np
from dashboard import DashboardManager

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sarawak-energy-robots'
socketio = SocketIO(app, cors_allowed_origins="*")

SHARED_DATA_PATH = "/app/shared-data"
os.makedirs(SHARED_DATA_PATH, exist_ok=True)

dashboard_manager = DashboardManager()

class RobotSystem:
    def __init__(self):
        self.robots = {
            'robot_1': {
                'id': 'ROBOT_001',
                'name': 'Security Patrol Robot',
                'current_floor': 1,
                'status': 'active',
                'battery_level': 85,
                'last_seen': datetime.now().isoformat(),
                'assigned_floors': [1, 2, 3],
                'capabilities': ['visitor_tracking', 'security_patrol', 'access_control']
            },
            'robot_2': {
                'id': 'ROBOT_002', 
                'name': 'Maintenance Robot',
                'current_floor': 4,
                'status': 'active',
                'battery_level': 92,
                'last_seen': datetime.now().isoformat(),
                'assigned_floors': [4, 5],
                'capabilities': ['temperature_control', 'equipment_monitoring', 'maintenance_alerts']
            }
        }
        
        self.authorized_visitors = {}  # visitor_id -> visitor_info
        self.alerts = []
        self.sensor_alerts = []
        self.running = True
        
        # Start robot data generation
        self.start_robot_simulation()
    
    def start_robot_simulation(self):
        """Start robot data simulation in background"""
        def simulate_robots():
            while self.running:
                try:
                    self.update_robot_status()
                    self.generate_robot_sensor_data()
                    time.sleep(15)  # Update every 15 seconds
                except Exception as e:
                    print(f"Robot simulation error: {e}")
                    time.sleep(15)
        
        robot_thread = threading.Thread(target=simulate_robots, daemon=True)
        robot_thread.start()
    
    def update_robot_status(self):
        """Update robot status and positions"""
        for robot_id, robot in self.robots.items():
            # Simulate battery drain and movement
            robot['battery_level'] = max(20, robot['battery_level'] - np.random.uniform(0.1, 0.5))
            
            # Occasionally move to different floors
            if np.random.random() < 0.3:  # 30% chance to move
                robot['current_floor'] = np.random.choice(robot['assigned_floors'])
            
            robot['last_seen'] = datetime.now().isoformat()
            
            # Check for low battery
            if robot['battery_level'] < 30:
                self.create_alert(f"Low battery warning for {robot['name']}: {robot['battery_level']:.1f}%", 'warning')
        
        # Emit real-time updates
        socketio.emit('robot_status_update', self.robots)
    
    def generate_robot_sensor_data(self):
        """Generate sensor data from robots"""
        for robot_id, robot in self.robots.items():
            sensor_data = {
                'robot_id': robot['id'],
                'timestamp': datetime.now().isoformat(),
                'floor': robot['current_floor'],
                'temperature': round(22 + np.random.normal(0, 2), 1),  # Room temperature
                'humidity': round(45 + np.random.normal(0, 5), 1),
                'light_level': round(np.random.uniform(200, 800), 1),  # Lux
                'motion_detected': np.random.random() < 0.2,  # 20% chance
                'air_quality': round(np.random.uniform(20, 80), 1),  # AQI
                'noise_level': round(np.random.uniform(30, 70), 1)  # dB
            }
            
            # Save sensor data
            self.save_robot_sensor_data(sensor_data)
            
            # Update dashboard
            dashboard_manager.update_robot_data(robot_id, sensor_data)
        
        # Emit sensor updates
        socketio.emit('sensor_data_update', {'timestamp': datetime.now().isoformat()})
    
    def save_robot_sensor_data(self, data):
        """Save robot sensor data to file"""
        today = datetime.now().strftime('%Y-%m-%d')
        filename = os.path.join(SHARED_DATA_PATH, f"robot_sensors_{today}.json")
        
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                existing_data = json.load(f)
        else:
            existing_data = []
        
        existing_data.append(data)
        
        with open(filename, 'w') as f:
            json.dump(existing_data, f, indent=2)
    
    def add_authorized_visitor(self, visitor_data):
        """Add authorized visitor from verification system"""
        visitor_id = visitor_data['visitor_id']
        self.authorized_visitors[visitor_id] = visitor_data
        
        alert_msg = f"New authorized visitor: {visitor_data['name']} - Floor {visitor_data['destination_floor']}"
        self.create_alert(alert_msg, 'info')
        
        print(f"Added authorized visitor: {visitor_data['name']}")
        
        # Emit visitor update
        socketio.emit('new_visitor', visitor_data)
    
    def handle_threshold_alert(self, alert_data):
        """Handle sensor threshold violations from ML system"""
        self.sensor_alerts.append(alert_data)
        
        violations_str = ", ".join(alert_data['violations'])
        alert_msg = f"URGENT: Oil parameter threshold exceeded - {violations_str}"
        self.create_alert(alert_msg, 'critical')
        
        # Simulate robot response to temperature control
        if any('Temperature' in v for v in alert_data['violations']):
            self.simulate_temperature_adjustment(alert_data)
        
        print(f"Received threshold alert: {violations_str}")
        
        # Emit threshold alert
        socketio.emit('threshold_alert', alert_data)
    
    def simulate_temperature_adjustment(self, alert_data):
        """Simulate robot adjusting oil container temperature"""
        maintenance_robot = self.robots['robot_2']
        
        if 'temperature_control' in maintenance_robot['capabilities']:
            adjustment_data = {
                'robot_id': maintenance_robot['id'],
                'action': 'temperature_adjustment',
                'timestamp': datetime.now().isoformat(),
                'target_temperature': 75.0,  # Target temperature
                'sensor_id': alert_data['sensor_id'],
                'status': 'adjusting'
            }
            
            # Save adjustment action
            adjustment_file = os.path.join(SHARED_DATA_PATH, f"temp_adjustment_{datetime.now().timestamp()}.json")
            with open(adjustment_file, 'w') as f:
                json.dump(adjustment_data, f, indent=2)
            
            self.create_alert(f"Maintenance robot adjusting oil container temperature", 'info')
            
            # Emit adjustment notification
            socketio.emit('temperature_adjustment', adjustment_data)
    
    def check_visitor_floor_access(self, visitor_id, current_floor):
        """Check if visitor is on authorized floor"""
        if visitor_id not in self.authorized_visitors:
            return False, "Unauthorized visitor detected"
        
        visitor = self.authorized_visitors[visitor_id]
        authorized_floor = visitor['destination_floor']
        
        if current_floor != authorized_floor:
            alert_msg = f"SECURITY ALERT: {visitor['name']} detected on floor {current_floor} (authorized: {authorized_floor})"
            self.create_alert(alert_msg, 'security')
            return False, alert_msg
        
        return True, "Access authorized"
    
    def create_alert(self, message, alert_type='info'):
        """Create system alert"""
        alert = {
            'id': len(self.alerts) + 1,
            'timestamp': datetime.now().isoformat(),
            'message': message,
            'type': alert_type,  # info, warning, critical, security
            'acknowledged': False
        }
        
        self.alerts.append(alert)
        
        # Keep only last 100 alerts
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]
        
        # Emit alert
        socketio.emit('new_alert', alert)
    
    def get_dashboard_data(self):
        """Get comprehensive dashboard data"""
        return {
            'robots': self.robots,
            'authorized_visitors': len(self.authorized_visitors),
            'active_alerts': len([a for a in self.alerts if not a['acknowledged']]),
            'recent_alerts': self.alerts[-10:],  # Last 10 alerts
            'sensor_data': dashboard_manager.get_latest_sensor_data(),
            'system_status': 'operational',
            'last_updated': datetime.now().isoformat()
        }

# Initialize robot system
robot_system = RobotSystem()

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/dashboard_data')
def get_dashboard_data():
    """API endpoint for dashboard data"""
    return jsonify(robot_system.get_dashboard_data())

@app.route('/api/robots')
def get_robots():
    """Get robot status"""
    return jsonify(robot_system.robots)

@app.route('/api/alerts')
def get_alerts():
    """Get system alerts"""
    return jsonify({
        'alerts': robot_system.alerts,
        'total': len(robot_system.alerts),
        'unacknowledged': len([a for a in robot_system.alerts if not a['acknowledged']])
    })

@app.route('/api/acknowledge_alert/<int:alert_id>', methods=['POST'])
def acknowledge_alert(alert_id):
    """Acknowledge an alert"""
    for alert in robot_system.alerts:
        if alert['id'] == alert_id:
            alert['acknowledged'] = True
            socketio.emit('alert_acknowledged', alert)
            return jsonify({'success': True})
    
    return jsonify({'success': False, 'message': 'Alert not found'}), 404

@app.route('/new_visitor', methods=['POST'])
def new_visitor():
    """Receive new visitor data from verification system"""
    try:
        visitor_data = request.get_json()
        robot_system.add_authorized_visitor(visitor_data)
        
        # Create trigger file for Jenkins
        trigger_file = os.path.join(SHARED_DATA_PATH, f"trigger_robot-pipeline_{datetime.now().timestamp()}.txt")
        with open(trigger_file, 'w') as f:
            f.write(f"Robot pipeline triggered by new visitor at {datetime.now().isoformat()}")
        
        return jsonify({'success': True, 'message': 'Visitor authorized'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/threshold_alert', methods=['POST'])
def threshold_alert():
    """Receive threshold alerts from sensor ML system"""
    try:
        alert_data = request.get_json()
        robot_system.handle_threshold_alert(alert_data)
        
        # Create trigger file for Jenkins
        trigger_file = os.path.join(SHARED_DATA_PATH, f"trigger_robot-threshold-response_{datetime.now().timestamp()}.txt")
        with open(trigger_file, 'w') as f:
            f.write(f"Robot threshold response triggered at {datetime.now().isoformat()}")
        
        return jsonify({'success': True, 'message': 'Alert processed'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/check_visitor_access', methods=['POST'])
def check_visitor_access():
    """Check visitor floor access"""
    try:
        data = request.get_json()
        visitor_id = data.get('visitor_id')
        current_floor = data.get('current_floor')
        
        authorized, message = robot_system.check_visitor_floor_access(visitor_id, current_floor)
        
        return jsonify({
            'authorized': authorized,
            'message': message
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'service': 'robot-system'})

# WebSocket events
@socketio.on('connect')
def handle_connect():
    print('Client connected to robot system')
    emit('connected', {'status': 'Connected to Robot System'})

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected from robot system')

@socketio.on('request_dashboard_update')
def handle_dashboard_update():
    emit('dashboard_data', robot_system.get_dashboard_data())

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
