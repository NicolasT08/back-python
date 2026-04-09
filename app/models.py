from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid

db = SQLAlchemy()

def generate_uuid():
    return str(uuid.uuid4())

class Room(db.Model):
    __tablename__ = 'room'
    roomId = db.Column(db.String(50), primary_key=True, default=generate_uuid)
    floor = db.Column(db.Integer)
    roomNumber = db.Column(db.String(50))
    roomPavilion = db.Column(db.String(50))
    patients = db.relationship('Patient', backref='room_rel', lazy=True)

class AlertType(db.Model):
    __tablename__ = 'alert_type'
    alertTypeId = db.Column(db.String(50), primary_key=True, default=generate_uuid)
    name = db.Column(db.String(50))
    code = db.Column(db.String(20))
    description = db.Column(db.Text) 
class Wearable(db.Model):
    __tablename__ = 'wearable'
    wearableId = db.Column(db.String(50), primary_key=True, default=generate_uuid)
    macAddress = db.Column(db.String(20))
    batteryLevel = db.Column(db.Integer)
    isActive = db.Column(db.Boolean, default=True)

class MedicalCondition(db.Model):
    __tablename__ = 'medical_condition'
    conditionId = db.Column(db.String(50), primary_key=True, default=generate_uuid)
    name = db.Column(db.String(50))
    diagnostic = db.Column(db.Text) 
    allergenType = db.Column(db.String(50), nullable=True)
    isContagious = db.Column(db.Boolean, nullable=True)
    transmissionRoute = db.Column(db.String(60), nullable=True)

class EmergencyContact(db.Model):
    __tablename__ = 'emergency_contact'
    contactId = db.Column(db.String(50), primary_key=True, default=generate_uuid)
    firstName = db.Column(db.String(50))
    lastName = db.Column(db.String(50))
    phone = db.Column(db.String(50))
    mail = db.Column(db.String(50))

class Patient(db.Model):
    __tablename__ = 'patient'
    patientId = db.Column(db.String(50), primary_key=True, default=generate_uuid)
    firstName = db.Column(db.String(50), nullable=False)
    lastName = db.Column(db.String(50), nullable=False)
    dateOfBirth = db.Column(db.DateTime)
    roomId = db.Column(db.String(50), db.ForeignKey('room.roomId'))
    
    patient_wearables = db.relationship('PatientWearable', back_populates='patient', cascade="all, delete-orphan")
    patient_conditions = db.relationship('PatientCondition', back_populates='patient', cascade="all, delete-orphan")
    patient_contacts = db.relationship('PatientContact', back_populates='patient', cascade="all, delete-orphan")


class PatientWearable(db.Model):
    __tablename__ = 'PatientWearable'
    patientId = db.Column(db.String(50), db.ForeignKey('patient.patientId'), primary_key=True)
    wearableId = db.Column(db.String(50), db.ForeignKey('wearable.wearableId'), primary_key=True)
    assignedDate = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship('Patient', back_populates='patient_wearables')
    wearable = db.relationship('Wearable')

class PatientCondition(db.Model):
    __tablename__ = 'PatientCondition'
    patientId = db.Column(db.String(50), db.ForeignKey('patient.patientId'), primary_key=True)
    conditionId = db.Column(db.String(50), db.ForeignKey('medical_condition.conditionId'), primary_key=True)
    diagnostic = db.Column(db.Text)

    patient = db.relationship('Patient', back_populates='patient_conditions')
    condition = db.relationship('MedicalCondition')

class PatientContact(db.Model):
    __tablename__ = 'PatientContact'
    patientId = db.Column(db.String(50), db.ForeignKey('patient.patientId'), primary_key=True)
    contactId = db.Column(db.String(50), db.ForeignKey('emergency_contact.contactId'), primary_key=True)
    relationship = db.Column(db.String(50))

    patient = db.relationship('Patient', back_populates='patient_contacts')
    contact = db.relationship('EmergencyContact')

class Alert(db.Model):
    __tablename__ = 'alert'
    alertId = db.Column(db.String(50), primary_key=True, default=generate_uuid)
    patientId = db.Column(db.String(50), db.ForeignKey('patient.patientId'))
    wearableId = db.Column(db.String(50), db.ForeignKey('wearable.wearableId'))
    alertStatus = db.Column(db.String(30))
    alertLevel = db.Column(db.String(30))
    alertType = db.Column(db.String(50), db.ForeignKey('alert_type.alertTypeId'))
    nurseId = db.Column(db.String(50))
    createdAt = db.Column(db.DateTime, default=datetime.utcnow)
    resolvedAt = db.Column(db.DateTime, nullable=True)