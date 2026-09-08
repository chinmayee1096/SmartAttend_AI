"""Quality-filtered LBPH training. Run from the project venv."""
from pathlib import Path
from datetime import datetime
import json
import shutil
import hashlib
import cv2
import numpy as np
from face_pipeline import valid_sample, prepare_face


def _retire_model(destination, base, section):
    """Archive an unusable model and remove it from live recognition."""
    if not destination.exists():
        return
    backup = base.parent / 'model_backups' / datetime.now().strftime('%Y%m%d_%H%M%S_%f') / section.relative_to(base)
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(destination, backup / 'trainer.yml')
    destination.unlink()


def train_all(base):
    base = Path(base)
    report = []
    for section in sorted(base.glob('*/*')):
        if not (section / 'faces').is_dir():
            continue
        images, labels, held = [], [], []
        section_rows = []
        for student in sorted((section / 'faces').iterdir()):
            if not student.is_dir() or not student.name.isdigit():
                continue
            accepted, seen = [], set()
            paths = sorted(student.glob('*.jpg'))
            for path in paths:
                img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if not valid_sample(img):
                    continue
                face = prepare_face(img)
                digest = hashlib.sha256(face.tobytes()).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                accepted.append(face)
            row = {'section': str(section.relative_to(base)), 'roll': student.name,
                   'total': len(paths), 'accepted': len(accepted), 'excluded': len(paths)-len(accepted)}
            if len(accepted) < 10:
                row['status'] = 'Needs recapture: fewer than 10 valid unique samples'
                section_rows.append(row)
                continue
            label = int(student.name)
            split = max(2, len(accepted)//5)
            held.extend((face,label) for face in accepted[-split:])
            images.extend(accepted[:-split]); labels.extend([label]*(len(accepted)-split))
            row['status'] = 'Trained'
            section_rows.append(row)
        destination = section / 'trainer.yml'
        if images:
            model = cv2.face.LBPHFaceRecognizer_create()
            model.train(images, np.array(labels, dtype=np.int32))
            total_trials = 0
            total_correct = 0
            validation_passed = True
            for row in section_rows:
                trials = [(im,label) for im,label in held if label == int(row['roll'])]
                if trials:
                    predictions = [model.predict(im) for im,label in trials]
                    row['held_out'] = len(trials)
                    row['correct_under_55'] = sum(pred == int(row['roll']) and score < 55 for pred,score in predictions)
                    row['validation_accuracy'] = round(row['correct_under_55'] / len(trials), 3)
                    total_trials += len(trials)
                    total_correct += row['correct_under_55']
                    if row['validation_accuracy'] < 0.7:
                        row['status'] = 'Validation failed: recapture clear images of this student'
                        validation_passed = False
                    else:
                        row['status'] = 'Trained: validation passed'
            if not total_trials or total_correct / total_trials < 0.8:
                validation_passed = False
            if not validation_passed:
                _retire_model(destination, base, section)
                report.extend(section_rows)
                continue
            # Validation above uses unseen samples; final fit uses every accepted sample.
            images.extend(im for im,label in held); labels.extend(label for im,label in held)
            model.train(images, np.array(labels, dtype=np.int32))
            if destination.exists():
                backup = base.parent / 'model_backups' / datetime.now().strftime('%Y%m%d_%H%M%S') / section.relative_to(base)
                backup.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup / 'trainer.yml')
            temporary = section / 'trainer.pending.yml'
            model.save(str(temporary)); temporary.replace(destination)
        else:
            _retire_model(destination, base, section)
        report.extend(section_rows)
    (base / 'training_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

if __name__ == '__main__':
    print(json.dumps(train_all(Path(__file__).resolve().parent / 'dataset' / 'college_faces'),indent=2))
