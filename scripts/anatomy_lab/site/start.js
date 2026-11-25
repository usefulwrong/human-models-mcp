import("./viewer.js?v=moving-1").catch(error => {
  document.getElementById("message").textContent = `Could not open the anatomy atlas. ${error.message}`;
});
