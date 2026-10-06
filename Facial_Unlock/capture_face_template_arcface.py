import cv2
import insightface
import numpy as np

model = insightface.app.FaceAnalysis(name="buffalo_l")
model.prepare(ctx_id=0, det_size=(640, 640))

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
print("Look at the camera. Press SPACE to capture your face template.")

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    faces = model.get(frame)

    if faces:
        face = faces[0]
        x1, y1, x2, y2 = face.bbox.astype(int)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0,255,0), 2)

    cv2.imshow("Capture Template", frame)

    key = cv2.waitKey(1)
    if key == 32 and faces:  # SPACE
        embedding = face.embedding
        np.save("amrit_arcface_template.npy", embedding)
        print("Saved ArcFace template.")
        break
    elif key == 27:
        break

cap.release()
cv2.destroyAllWindows()
