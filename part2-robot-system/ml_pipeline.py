import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor, IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler
import joblib
import json
import os
from datetime import datetime, timedelta
import glob

class MLPipeline:
    def __init__(self):
        self.models_path = "/app/models"
        self.sensor_data_path = "/app/sensor-data"
        self.model = None
        self.scaler = None
        self.anomaly_detector = None
        self.model_metadata = {}
    
    def load_sensor_data(self, days_back=7):
        """Load sensor data from the last N days"""
        all_data = []
        
        for i in range(days_back):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            filename = os.path.join(self.sensor_data_path, f"sensor_data_{date}.json")
            
            if os.path.exists(filename):
                with open(filename, 'r') as f:
                    daily_data = json.load(f)
                    all_data.extend(daily_data)
        
        if not all_data:
            # Generate some initial training data if no data exists
            return self.generate_synthetic_training_data()
        
        # Convert to DataFrame
        df = pd.DataFrame(all_data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Feature engineering
        df['hour'] = df['timestamp'].dt.hour
        df['day_of_week'] = df['timestamp'].dt.dayofweek
        df['temp_pressure_ratio'] = df['temperature'] / df['pressure']
        df['viscosity_flow_ratio'] = df['viscosity'] / df['flow_rate']
        
        return df
    
    def generate_synthetic_training_data(self, n_samples=1000):
        """Generate synthetic training data for initial model"""
        np.random.seed(42)
        
        data = []
        for i in range(n_samples):
            base_temp = 75 + np.random.normal(0, 8)
            base_pressure = 120 + np.random.normal(0, 15)
            base_viscosity = 35 + np.random.normal(0, 5)
            
            # Add correlations
            if base_temp > 80:
                base_viscosity *= 0.9
                base_pressure *= 1.1
            
            timestamp = datetime.now() - timedelta(
                days=np.random.randint(1, 30),
                hours=np.random.randint(0, 24),
                minutes=np.random.randint(0, 60)
            )
            
            data.append({
                'timestamp': timestamp.isoformat(),
                'sensor_id': f"OIL_SENSOR_{np.random.randint(1, 6)}",
                'temperature': round(base_temp, 2),
                'pressure': round(base_pressure, 2),
                'viscosity': round(base_viscosity, 2),
                'flow_rate': round(45 + np.random.normal(0, 8), 2),
                'contamination_level': round(np.random.uniform(0.1, 10.0), 2)
            })
        
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['day_of_week'] = df['timestamp'].dt.dayofweek
        df['temp_pressure_ratio'] = df['temperature'] / df['pressure']
        df['viscosity_flow_ratio'] = df['viscosity'] / df['flow_rate']
        
        return df
    
    def prepare_features(self, df):
        """Prepare features for ML model"""
        feature_columns = [
            'temperature', 'pressure', 'viscosity', 'flow_rate', 
            'contamination_level', 'hour', 'day_of_week',
            'temp_pressure_ratio', 'viscosity_flow_ratio'
        ]
        
        X = df[feature_columns].fillna(0)
        
        # Target: predict next temperature based on current conditions
        y = df['temperature'].shift(-1).fillna(df['temperature'].mean())
        
        return X, y, feature_columns
    
    def train_model(self):
        """Train ML model with current data"""
        try:
            print("Loading sensor data...")
            df = self.load_sensor_data()
            
            if len(df) < 50:
                return {
                    'success': False,
                    'message': 'Insufficient data for training (minimum 50 samples required)',
                    'data_points': len(df)
                }
            
            print(f"Training with {len(df)} data points...")
            
            # Prepare features
            X, y, feature_columns = self.prepare_features(df)
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42
            )
            
            # Scale features
            self.scaler = StandardScaler()
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)
            
            # Train regression model for temperature prediction
            self.model = RandomForestRegressor(
                n_estimators=100,
                max_depth=10,
                random_state=42,
                n_jobs=-1
            )
            self.model.fit(X_train_scaled, y_train)
            
            # Train anomaly detection model
            self.anomaly_detector = IsolationForest(
                contamination=0.1,
                random_state=42
            )
            self.anomaly_detector.fit(X_train_scaled)
            
            # Evaluate model
            y_pred = self.model.predict(X_test_scaled)
            mse = mean_squared_error(y_test, y_pred)
            r2 = r2_score(y_test, y_pred)
            
            # Save model metadata
            self.model_metadata = {
                'training_timestamp': datetime.now().isoformat(),
                'data_points': len(df),
                'features': feature_columns,
                'mse': float(mse),
                'r2_score': float(r2),
                'model_version': f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            }
            
            # Save models
            model_file = os.path.join(self.models_path, 'temperature_prediction_model.joblib')
            scaler_file = os.path.join(self.models_path, 'scaler.joblib')
            anomaly_file = os.path.join(self.models_path, 'anomaly_detector.joblib')
            metadata_file = os.path.join(self.models_path, 'model_metadata.json')
            
            joblib.dump(self.model, model_file)
            joblib.dump(self.scaler, scaler_file)
            joblib.dump(self.anomaly_detector, anomaly_file)
            
            with open(metadata_file, 'w') as f:
                json.dump(self.model_metadata, f, indent=2)
            
            print(f"Model trained successfully! R² Score: {r2:.4f}")
            
            return {
                'success': True,
                'message': 'Model trained successfully',
                'metrics': {
                    'mse': float(mse),
                    'r2_score': float(r2),
                    'data_points': len(df)
                },
                'model_version': self.model_metadata['model_version']
            }
            
        except Exception as e:
            print(f"Error training model: {e}")
            return {
                'success': False,
                'message': f'Training failed: {str(e)}'
            }
    
    def load_model(self):
        """Load trained model from disk"""
        try:
            model_file = os.path.join(self.models_path, 'temperature_prediction_model.joblib')
            scaler_file = os.path.join(self.models_path, 'scaler.joblib')
            anomaly_file = os.path.join(self.models_path, 'anomaly_detector.joblib')
            metadata_file = os.path.join(self.models_path, 'model_metadata.json')
            
            if all(os.path.exists(f) for f in [model_file, scaler_file, metadata_file]):
                self.model = joblib.load(model_file)
                self.scaler = joblib.load(scaler_file)
                
                if os.path.exists(anomaly_file):
                    self.anomaly_detector = joblib.load(anomaly_file)
                
                with open(metadata_file, 'r') as f:
                    self.model_metadata = json.load(f)
                
                return True
            else:
                # Train initial model if none exists
                result = self.train_model()
                return result.get('success', False)
                
        except Exception as e:
            print(f"Error loading model: {e}")
            return False
    
    def predict(self, sensor_data):
        """Make prediction using trained model"""
        if self.model is None or self.scaler is None:
            if not self.load_model():
                return {'error': 'No trained model available'}
        
        try:
            # Prepare features
            features = np.array([[
                sensor_data.get('temperature', 75),
                sensor_data.get('pressure', 120),
                sensor_data.get('viscosity', 35),
                sensor_data.get('flow_rate', 45),
                sensor_data.get('contamination_level', 2),
                datetime.now().hour,
                datetime.now().weekday(),
                sensor_data.get('temperature', 75) / sensor_data.get('pressure', 120),
                sensor_data.get('viscosity', 35) / sensor_data.get('flow_rate', 45)
            ]])
            
            # Scale features
            features_scaled = self.scaler.transform(features)
            
            # Make prediction
            prediction = self.model.predict(features_scaled)[0]
            
            # Check for anomaly
            anomaly_score = -1
            is_anomaly = False
            if self.anomaly_detector is not None:
                anomaly_score = self.anomaly_detector.decision_function(features_scaled)[0]
                is_anomaly = self.anomaly_detector.predict(features_scaled)[0] == -1
            
            return {
                'predicted_temperature': float(prediction),
                'anomaly_score': float(anomaly_score),
                'is_anomaly': bool(is_anomaly),
                'model_version': self.model_metadata.get('model_version', 'unknown')
            }
            
        except Exception as e:
            return {'error': f'Prediction failed: {str(e)}'}
    
    def get_model_info(self):
        """Get information about current model"""
        if not self.model_metadata:
            self.load_model()
        
        return {
            'model_loaded': self.model is not None,
            'metadata': self.model_metadata,
            'models_available': os.path.exists(os.path.join(self.models_path, 'temperature_prediction_model.joblib'))
        }
