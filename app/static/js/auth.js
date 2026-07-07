function setupDropzone(zoneEl, inputEl, onFileSelected) {
  zoneEl.addEventListener("click", () => inputEl.click());
  inputEl.addEventListener("change", () => {
    if (inputEl.files[0]) onFileSelected(inputEl.files[0]);
  });
  ["dragover", "dragleave", "drop"].forEach((evt) => {
    zoneEl.addEventListener(evt, (e) => e.preventDefault());
  });
  zoneEl.addEventListener("dragover", () => zoneEl.classList.add("dragover"));
  zoneEl.addEventListener("dragleave", () => zoneEl.classList.remove("dragover"));
  zoneEl.addEventListener("drop", (e) => {
    zoneEl.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file) {
      inputEl.files = e.dataTransfer.files;
      onFileSelected(file);
    }
  });
}

function fetchMe() {
  return apiGet("/api/me");
}

function login(email, password) {
  return apiPostJson("/api/login", { email, password });
}

function register(email, password, file) {
  const formData = new FormData();
  formData.append("email", email);
  formData.append("password", password);
  if (file) formData.append("file", file);
  return apiPostForm("/api/register", formData);
}

function logout() {
  return apiPostJson("/api/logout", {});
}

function updateData(file) {
  const formData = new FormData();
  formData.append("file", file);
  return apiPostForm("/api/upload", formData);
}
