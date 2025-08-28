import face_recognition
import cv2
import numpy as np

class FaceVerification:
    def __init__(self):
        self.known_faces = []
        self.known_names = []
    
    def add_known_face(self, image_path, name):
        """Add a known face to the database"""
        try:
            image = face_recognition.load_image_file(image_path)
            face_encodings = face_recognition.face_encodings(image)
            
            if face_encodings:
                self.known_faces.append(face_encodings[0])
                self.known_names.append(name)
                return True
            return False
        except Exception as e:
            print(f"Error adding known face: {e}")
            return False
    
    def verify_face(self, image):
        """Verify if the face matches any known faces"""
        try:
            face_encodings = face_recognition.face_encodings(image)
            
            if not face_encodings:
                return False, "No face detected"
            
            face_encoding = face_encodings[0]
            
            # Compare with known faces
            matches = face_recognition.compare_faces(
                self.known_faces, face_encoding, tolerance=0.6
            )
            
            if True in matches:
                match_index = matches.index(True)
                return True, self.known_names[match_index]
            
            return False, "Unknown person"
        except Exception as e:
            return False, f"Verification error: {str(e)}"